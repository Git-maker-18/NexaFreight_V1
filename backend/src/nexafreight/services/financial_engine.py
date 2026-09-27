"""Financial impact calculations for shipment routing decisions.

Pure functions with no I/O, database access, or side effects — fully
deterministic and unit-testable. Used by the alert engine, reroute
engine, SLA checker (Definitive Plan Phases 1-6), and the shipment
financials endpoint.

Rates & caps (calibrated to published anchors — Regulatory_Tax_Reference.md SS8;
fx USD/INR = 88):
- SLA penalty: LD norms — 0.5% of order value per WEEK late (WEEKLY rounding),
  capped at 10% (calculate_sla_penalty_weekly). The legacy 5%/day function is
  kept for backward compatibility but overstates LD norms ~7x.
- Demurrage: 4 free days, then Rs5,500/container/day (= $57.40 at fx 95.8;
  JNPT band Rs3-8k/box/day); after 7 billable days the rate doubles.
- Freight: per-mode $/tonne-km (SEA 0.012 mainline; AIR 0.9 = NCAER Rs72/tkm
  anchor; ROAD 0.036 = Rs3.2/tkm bottom-up; RAIL 0.016 = Rs1.4/tkm class-avg).
- CO2: per-mode g/tonne-km emission factors (SEA 8.0 = GLEC v3.2 container
  band 7.6-9.1 mix mid, AIR 500, ROAD 62, RAIL 22) priced at $0.08/kg
  (CBAM transitory price anchor).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from nexafreight.enums import TransportMode

# ---------------------------------------------------------------------------
# Rate constants
# ---------------------------------------------------------------------------

#: SLA penalty rate per day late (fraction of order revenue).
#: DEPRECATED for decision math — kept only for backward compatibility.
#: LD norms are 0.5%/week (see SLA_PENALTY_PCT_PER_WEEK); 5%/day ≈ 7x norms.
SLA_PENALTY_PCT_PER_DAY: float = 0.05

#: SLA penalty rate per WEEK late per LD norms (fraction of order value).
SLA_PENALTY_PCT_PER_WEEK: float = 0.005

#: SLA penalty hard cap as a fraction of order revenue.
SLA_PENALTY_CAP_PCT: float = 0.10

#: Free demurrage days before charges start.
DEMURRAGE_FREE_DAYS: int = 4

#: Demurrage charge per container-day, tier 1 (days 1-7 after free period).
#: Rs5,500/box/day (JNPT band mid, Regulatory doc SS8) / fx 95.8 = $57.40.
DEMURRAGE_DAILY_RATE: float = 5500.0 / 95.8

#: Billable days at tier 1 before the rate doubles.
DEMURRAGE_TIER1_DAYS: int = 7

#: Tier-2 rate multiplier applied beyond tier 1.
DEMURRAGE_TIER2_MULTIPLIER: float = 2.0

#: Nominal freight rates, USD per tonne-km, by transport mode.
#: Anchors: SEA $0.012 mainline (INDUSTRY); AIR $0.9 = NCAER Rs72/tkm / fx 88
#: (closes E9, was 1.8 = 2x the national anchor); ROAD Rs3.2/tkm / 95.8 = 0.0334
#: (DERIVED bottom-up, was 0.06); RAIL Rs1.4/tkm class-avg / 95.8 = 0.0146.
FREIGHT_RATE_PER_T_KM: dict[str, float] = {
    "SEA": 0.012,
    "AIR": 0.9,
    "ROAD": 0.0334,
    "RAIL": 0.0146,
}

#: CO2 emission factors, grams per tonne-km, by transport mode.
#: SEA: GLEC v3.2 deep-sea container 7.6 (>=8k TEU) - 9.1 (3-8k TEU);
#: 8.0 = mid for the modeled vessel mix (was 6.5, below the entire band).
CO2_G_PER_T_KM: dict[str, float] = {
    "SEA": 8.0,
    "AIR": 500.0,
    "ROAD": 62.0,
    "RAIL": 22.0,
}

#: Carbon price — USD per kg CO2.
CARBON_COST_PER_KG: float = 0.08


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderFinancialInput:
    """Input data for calculating one order's financial impact."""

    revenue: float
    penalty_pct: float  # e.g., 0.05 for 5%
    days_late: int
    extra_days: int  # Days beyond planned delivery
    free_days: int  # Free demurrage days
    daily_rate: float  # Demurrage cost per day
    co2_delta_kg: float  # CO2 change (positive = increase, negative = decrease)


@dataclass(frozen=True)
class OrderFinancialImpact:
    """Calculated financial impact for one order."""

    sla_penalty: float
    demurrage: float
    carbon_cost: float
    total_impact_usd: float


@dataclass(frozen=True)
class ShipmentFinancialImpact:
    """Aggregated financial impact for a shipment with multiple orders."""

    per_order_impacts: list[OrderFinancialImpact]
    total_impact_usd: float


@dataclass(frozen=True)
class PnLSnapshot:
    """Profit-and-loss snapshot for one shipment.

    Deliberately a plain value object: the caller supplies the components
    and everything else is derived here so there is exactly one place the
    arithmetic lives.
    """

    revenue_usd: float
    shipping_cost_usd: float
    sla_penalty_usd: float
    demurrage_usd: float
    freight_cost_usd: float
    carbon_cost_usd: float
    total_costs_usd: float
    margin_usd: float
    margin_pct: float | None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SLA penalty
# ---------------------------------------------------------------------------


def calculate_sla_penalty(
    revenue: float,
    penalty_pct: float,
    days_late: int,
    *,
    cap_pct: float = SLA_PENALTY_CAP_PCT,
) -> float:
    """Calculate SLA penalty for late delivery.

    Args:
        revenue: Order revenue (USD)
        penalty_pct: Penalty percentage per day late (e.g., 0.05 for 5%)
        days_late: Days past SLA deadline (negative or zero = no penalty)
        cap_pct: Hard cap on the penalty as a fraction of revenue
                 (Definitive Plan Phase 1 — capped at 10%)

    Returns:
        Penalty amount in USD (0.0 if not late).

    Formula:
        min(revenue * penalty_pct * days_late, revenue * cap_pct)

    Deprecated:
        Decision paths now use calculate_sla_penalty_weekly (LD norms). This
        per-day variant remains for backward compatibility only.
    """
    if days_late <= 0:
        return 0.0
    uncapped = revenue * penalty_pct * days_late
    cap = revenue * cap_pct
    return min(uncapped, cap)


def calculate_sla_penalty_weekly(
    revenue: float,
    pct_per_week: float,
    days_late: int,
    *,
    cap_pct: float = SLA_PENALTY_CAP_PCT,
) -> float:
    """Calculate SLA penalty per LD norms: pct per WEEK late, WEEKLY rounding.

    Indian LD practice accrues 0.5% of order value per week of delay (any part
    week rounds up to a full week), capped at 10% of order value. Callers pass
    pct_per_week/cap_pct as fractions (0.005 / 0.10) — typically read from
    params keys sla.penalty_pct_per_week (0.5) and sla.penalty_cap_pct (10.0),
    divided by 100.

    Formula:
        weeks_late = ceil(days_late / 7)
        min(revenue * pct_per_week * weeks_late, revenue * cap_pct)
    """
    if days_late <= 0:
        return 0.0
    weeks_late = math.ceil(days_late / 7)
    return min(revenue * pct_per_week * weeks_late, revenue * cap_pct)


# ---------------------------------------------------------------------------
# Demurrage
# ---------------------------------------------------------------------------


def calculate_demurrage(
    extra_days: int,
    free_days: int,
    daily_rate: float,
    *,
    tier1_days: int = DEMURRAGE_TIER1_DAYS,
    tier2_multiplier: float = DEMURRAGE_TIER2_MULTIPLIER,
) -> float:
    """Calculate tiered demurrage charges for container detention.

    Args:
        extra_days: Total days the container is held beyond planned delivery
        free_days: Free days before demurrage starts
        daily_rate: Tier-1 cost per billable day (USD)
        tier1_days: Billable days charged at the tier-1 rate
        tier2_multiplier: Tier-2 rate multiplier beyond tier 1

    Returns:
        Demurrage cost in USD, always >= 0.

    Formula:
        billable = extra_days - free_days
        tier1 = min(billable, tier1_days) * daily_rate
        tier2 = max(0, billable - tier1_days) * daily_rate * tier2_multiplier
    """
    if extra_days <= free_days:
        return 0.0
    billable = extra_days - free_days
    tier1 = min(billable, tier1_days) * daily_rate
    tier2 = max(0, billable - tier1_days) * daily_rate * tier2_multiplier
    return max(0.0, tier1 + tier2)


# ---------------------------------------------------------------------------
# Freight & carbon
# ---------------------------------------------------------------------------


def calculate_freight_cost(
    distance_km: float,
    weight_tonnes: float,
    mode: str | TransportMode,
) -> float:
    """Nominal carrier freight cost for one leg.

    rate($/t-km) x distance(km) x weight(t). The rates are documented
    assumptions (see module docstring) — good enough to rank options,
    not a quote engine.
    """
    rate = FREIGHT_RATE_PER_T_KM.get(str(mode), FREIGHT_RATE_PER_T_KM["SEA"])
    return rate * distance_km * weight_tonnes


def calculate_co2_kg(
    distance_km: float,
    weight_tonnes: float,
    mode: str | TransportMode,
) -> float:
    """CO2 emissions in kg for one leg (g/t-km factor × km × t ÷ 1000)."""
    factor = CO2_G_PER_T_KM.get(str(mode), CO2_G_PER_T_KM["SEA"])
    return factor * distance_km * weight_tonnes / 1000.0


def calculate_co2_cost(co2_kg: float) -> float:
    """Carbon cost (or savings when negative) at $0.08/kg."""
    return co2_kg * CARBON_COST_PER_KG


def calculate_carbon_cost(co2_delta_kg: float, cost_per_kg: float = CARBON_COST_PER_KG) -> float:
    """Backward-compatible alias: price a CO2 *delta*.

    Negative deltas (improvement) return a negative cost — kept so net
    impact comparisons across options stay properly signed.
    """
    return co2_delta_kg * cost_per_kg


# ---------------------------------------------------------------------------
# Order / shipment impact
# ---------------------------------------------------------------------------


def calculate_order_financial_impact(order_input: OrderFinancialInput) -> OrderFinancialImpact:
    """Calculate complete financial impact for one order.

    Args:
        order_input: All financial parameters for the order

    Returns:
        OrderFinancialImpact with individual components and total
    """
    sla_penalty = calculate_sla_penalty(
        revenue=order_input.revenue,
        penalty_pct=order_input.penalty_pct,
        days_late=order_input.days_late,
    )

    demurrage = calculate_demurrage(
        extra_days=order_input.extra_days,
        free_days=order_input.free_days,
        daily_rate=order_input.daily_rate,
    )

    carbon_cost = calculate_carbon_cost(
        co2_delta_kg=order_input.co2_delta_kg,
    )

    total = sla_penalty + demurrage + carbon_cost

    return OrderFinancialImpact(
        sla_penalty=sla_penalty,
        demurrage=demurrage,
        carbon_cost=carbon_cost,
        total_impact_usd=total,
    )


def calculate_shipment_financial_impact(
    orders: list[OrderFinancialInput],
) -> ShipmentFinancialImpact:
    """Calculate aggregated financial impact for a multi-order shipment.

    Args:
        orders: List of order financial inputs

    Returns:
        ShipmentFinancialImpact with per-order breakdown and shipment total
    """
    per_order_impacts = [calculate_order_financial_impact(order) for order in orders]

    total = sum(impact.total_impact_usd for impact in per_order_impacts)

    return ShipmentFinancialImpact(
        per_order_impacts=per_order_impacts,
        total_impact_usd=total,
    )


# ---------------------------------------------------------------------------
# P&L snapshot
# ---------------------------------------------------------------------------


def generate_pnl_snapshot(
    *,
    revenue_usd: float,
    shipping_cost_usd: float,
    sla_penalty_usd: float,
    demurrage_usd: float,
    freight_cost_usd: float,
    carbon_cost_usd: float,
) -> PnLSnapshot:
    """Profit-and-loss snapshot for a shipment.

    total_costs = shipping + freight + carbon + sla penalties + demurrage
    margin      = revenue - total_costs
    margin_pct  = margin / revenue (None when revenue <= 0)
    """
    warnings: list[str] = []

    total_costs = (
        shipping_cost_usd + freight_cost_usd + carbon_cost_usd + sla_penalty_usd + demurrage_usd
    )
    if carbon_cost_usd < 0:
        warnings.append("Carbon savings applied (negative carbon cost).")
    if sla_penalty_usd > 0 or demurrage_usd > 0:
        warnings.append("Projected penalties/demurrage included in costs.")

    margin = revenue_usd - total_costs
    margin_pct = margin / revenue_usd if revenue_usd > 0 else None

    if total_costs == 0:
        warnings.append("No cost inputs supplied.")
    if revenue_usd <= 0:
        warnings.append("No revenue recorded for this shipment.")
    if margin < 0:
        warnings.append("Do not ship: negative margin under current costs.")

    return PnLSnapshot(
        revenue_usd=revenue_usd,
        shipping_cost_usd=shipping_cost_usd,
        sla_penalty_usd=sla_penalty_usd,
        demurrage_usd=demurrage_usd,
        freight_cost_usd=freight_cost_usd,
        carbon_cost_usd=carbon_cost_usd,
        total_costs_usd=total_costs,
        margin_usd=margin,
        margin_pct=margin_pct,
        warnings=warnings,
    )


def assess_order_margin(
    *,
    revenue_usd: float,
    shipping_cost_usd: float,
    sla_penalty_usd: float,
    demurrage_usd: float,
    freight_cost_usd: float,
    carbon_cost_usd: float,
    min_margin_pct: float = 0.15,
) -> str:
    """GO / CAUTION / NO-GO margin assessment for a single order."""
    pnl = generate_pnl_snapshot(
        revenue_usd=revenue_usd,
        shipping_cost_usd=shipping_cost_usd,
        sla_penalty_usd=sla_penalty_usd,
        demurrage_usd=demurrage_usd,
        freight_cost_usd=freight_cost_usd,
        carbon_cost_usd=carbon_cost_usd,
    )
    if pnl.margin_pct is not None and pnl.margin_pct >= min_margin_pct:
        return f"GO: margin {pnl.margin_pct:.1%} meets target {min_margin_pct:.0%}."
    if pnl.margin_usd >= 0:
        return (
            f"CAUTION: margin {(pnl.margin_pct or 0.0):.1%} below target {min_margin_pct:.0%}; "
            "review consolidation options."
        )
    return f"NO-GO: negative margin ({pnl.margin_usd:,.0f} USD)."
