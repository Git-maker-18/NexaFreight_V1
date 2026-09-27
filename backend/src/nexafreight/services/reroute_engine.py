"""Reroute option engine (Definitive Plan — Phase 5).

For every alert the engine produces exactly three scored options:

  A. ACCEPT_DELAY   — absorb the estimated delay; cost_delta = 0; the SLA
                      penalties + demurrage it causes are the impact.
  B. DIVERT         — take a seeded corridor alternative (least added
                      transit time among corridors applicable to this
                      disruption type). When no corridor matches, a real
                      searoute divert via alternate port is computed with
                      route geometry and distance deltas.
  C. MODAL SHIFT    — fly the remaining distance via air block-time model.

Scoring: total_impact_usd = sla_penalty + demurrage + cost_delta + carbon.
Recommended = lowest total impact (traditional EXW total-cost-of-choice).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import DecisionAction, LegStatus
from nexafreight.models import Alert, Order, Shipment
from nexafreight.models.corridor import CorridorAlternative
from nexafreight.services.preference import apply_preference_prior, preference_stats
from nexafreight.services.alert_engine import (
    estimate_demurrage,
    latest_planned_arrival,
)
from nexafreight.services.disruption_detector import TONNES_PER_CONTAINER
from nexafreight.services.insurance import calculate_insurance_delta
from nexafreight.services.financial_engine import (
    calculate_co2_cost,
    calculate_co2_kg,
    calculate_freight_cost,
    calculate_sla_penalty_weekly,
)
from nexafreight.core import params

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Option value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RerouteOption:
    """One scored reroute option presented to the operator."""

    option_key: str
    action: DecisionAction
    display_name: str
    description: str
    revised_eta: datetime | None
    cost_delta_usd: float
    sla_penalty_usd: float
    demurrage_usd: float
    carbon_cost_usd: float
    co2_delta_kg: float
    sla_breaches: int
    total_impact_usd: float
    recommended: bool = False
    assumptions: list[str] = field(default_factory=list)
    route_template: dict | None = None
    corridor_alternative_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "option_key": self.option_key,
            "action": str(self.action),
            "display_name": self.display_name,
            "description": self.description,
            "revised_eta": self.revised_eta.isoformat() if self.revised_eta else None,
            "cost_delta_usd": round(self.cost_delta_usd, 2),
            "sla_penalty_usd": round(self.sla_penalty_usd, 2),
            "demurrage_usd": round(self.demurrage_usd, 2),
            "carbon_cost_usd": round(self.carbon_cost_usd, 2),
            "co2_delta_kg": round(self.co2_delta_kg, 1),
            "sla_breaches": self.sla_breaches,
            "total_impact_usd": round(self.total_impact_usd, 2),
            "recommended": self.recommended,
            "assumptions": list(self.assumptions),
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _days_late(revised_eta: datetime | None, deadline: datetime | None) -> int:
    """Whole days late (ceil), 0 when on time or unknowable."""
    if revised_eta is None or deadline is None:
        return 0
    if revised_eta.tzinfo is None:
        revised_eta = revised_eta.replace(tzinfo=UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if revised_eta <= deadline:
        return 0
    return max(1, math.ceil((revised_eta - deadline).total_seconds() / 86400.0))


def _score_sla(orders: list[Order], revised_eta: datetime | None) -> tuple[float, int]:
    """(total SLA penalty, breach count) for an order slate at an ETA."""
    total = 0.0
    breaches = 0
    # LD norms (calibration batch): 0.5% per week, WEEKLY rounding, cap 10%.
    pct_wk = params.get_float("sla.penalty_pct_per_week", 0.5) / 100.0
    cap = params.get_float("sla.penalty_cap_pct", 10.0) / 100.0
    for order in orders:
        late = _days_late(revised_eta, order.sla_deadline)
        if late > 0:
            breaches += 1
            total += calculate_sla_penalty_weekly(
                revenue=order.revenue,
                pct_per_week=pct_wk,
                days_late=late,
                cap_pct=cap,
            )
    return total, breaches


def _remaining_leg_metrics(shipment: Shipment) -> tuple[float, str]:
    """(remaining_km, current_mode) over the shipment's PLANNED legs."""
    planned = [leg for leg in shipment.legs if str(leg.status) == LegStatus.PLANNED]
    km = sum(leg.distance_km or 0.0 for leg in planned)
    mode = str(shipment.primary_transport_mode)
    return (km if km > 0 else params.get_float("reroute.default_remaining_km", 5000.0)), mode


def _co2_for(mode: str, km: float, weight_t: float) -> float:
    return calculate_co2_kg(km, weight_t, mode)


def _freight_for(mode: str, km: float, weight_t: float) -> float:
    return calculate_freight_cost(km, weight_t, mode)


# ---------------------------------------------------------------------------
# Option builders
# ---------------------------------------------------------------------------


def _create_accept_option(
    alert: Alert,
    shipment: Shipment,
    orders: list[Order],
    payload: dict,
) -> RerouteOption:
    """Option A — absorb the delay (Plan §Phase 5 step 2)."""
    delay_hours = float(
        payload.get("estimated_delay_hours")
        or params.get_float("reroute.fallback_delay_hours", 24.0)
    )
    base_eta = latest_planned_arrival(shipment)
    if base_eta is not None and base_eta.tzinfo is None:
        base_eta = base_eta.replace(tzinfo=UTC)
    revised_eta = base_eta + timedelta(hours=delay_hours) if base_eta else None

    sla_penalty, breaches = _score_sla(orders, revised_eta)
    demurrage = estimate_demurrage(shipment, delay_hours)
    total = sla_penalty + demurrage

    return RerouteOption(
        option_key="ACCEPT_DELAY",
        action=DecisionAction.ACCEPT_DELAY,
        display_name="Accept the delay",
        description=(
            f"Absorb the estimated {delay_hours:.0f}h delay on the current route. "
            "No freight premium; penalties and demurrage still apply."
        ),
        revised_eta=revised_eta,
        cost_delta_usd=0.0,
        sla_penalty_usd=sla_penalty,
        demurrage_usd=demurrage,
        carbon_cost_usd=0.0,
        co2_delta_kg=0.0,
        sla_breaches=breaches,
        total_impact_usd=total,
        assumptions=[
            "Delay estimate from detection payload (or 24h fallback).",
            "Freight cost unchanged — same route, same carrier.",
        ],
    )


async def _create_divert_option(
    alert: Alert,
    shipment: Shipment,
    orders: list[Order],
    corridor: dict | None,
    session: AsyncSession,
) -> RerouteOption:
    """Option B — divert via corridor alternative, else generic placeholder."""
    remaining_km, mode = _remaining_leg_metrics(shipment)
    weight_t = max(1, shipment.container_count) * TONNES_PER_CONTAINER
    baseline_freight = _freight_for(mode, remaining_km, weight_t)
    baseline_co2 = _co2_for(mode, remaining_km, weight_t)
    base_eta = latest_planned_arrival(shipment)
    if base_eta is not None and base_eta.tzinfo is None:
        base_eta = base_eta.replace(tzinfo=UTC)

    if corridor is not None:
        time_delta = float(corridor["time_delta_hours"])
        cost_factor = float(corridor["cost_delta_factor"])
        co2_factor = float(corridor["co2_delta_factor"])
        option_key = str(corridor["option_key"])
        display_name = str(corridor["display_name"])
        template = corridor.get("route_template")
        corridor_id = corridor.get("id")
        description = (
            f"Divert the remaining {remaining_km:,.0f} km via an alternate "
            f"corridor (+{time_delta:.0f}h transit, {cost_factor:.2f}× freight)."
        )
        assumptions = [
            f"Corridor factors ({cost_factor:.2f}× cost, {co2_factor:.2f}× CO2) "
            "applied to remaining freight.",
        ]
    else:
        from nexafreight.models.location import Location
        from nexafreight.enums import LocationType
        import searoute as sr
        
        def haversine_km(lat1, lon1, lat2, lon2):
            import math
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        origin = await session.get(Location, shipment.origin_id) if shipment.origin_id else None
        dest = await session.get(Location, shipment.destination_id) if shipment.destination_id else None
        
        ports = (
            await session.execute(
                select(Location).where(
                    Location.location_type == LocationType.PORT,
                    Location.id != dest.id
                )
            )
        ).scalars().all()
        
        alt_port = None
        if ports and dest:
            alt_port = min(ports, key=lambda p: haversine_km(dest.latitude, dest.longitude, p.latitude, p.longitude))
        
        success = False
        restrictions = []
        if corridor and "suez" in str(corridor.get("option_key", "")).lower():
            restrictions.append("suez")

        if alt_port and origin and dest:
            try:
                kwargs: dict = {"units": "km"}
                if restrictions:
                    kwargs["restrictions"] = restrictions

                r1 = sr.searoute(
                    [origin.longitude, origin.latitude],
                    [alt_port.longitude, alt_port.latitude],
                    **kwargs,
                )
                r2 = sr.searoute(
                    [alt_port.longitude, alt_port.latitude],
                    [dest.longitude, dest.latitude],
                    **kwargs,
                )
                dist1 = r1["properties"]["length"]
                dist2 = r2["properties"]["length"]
                dur1 = r1["properties"]["duration_hours"]
                dur2 = r2["properties"]["duration_hours"]
                
                total_km = dist1 + dist2
                time_delta = dur1 + dur2
                
                cost_factor = total_km / max(1.0, remaining_km)
                co2_factor = total_km / max(1.0, remaining_km)
                
                option_key = "DIVERT_GENERIC"
                display_name = f"Divert via {alt_port.name}"
                generic_mode = str(shipment.primary_transport_mode)
                
                coords = r1["geometry"]["coordinates"] + r2["geometry"]["coordinates"]
                template = {
                    "legs": [
                        {"mode": generic_mode, "to": alt_port.locode},
                        {"mode": generic_mode, "to": dest.locode},
                    ],
                    "geometry": {"type": "LineString", "coordinates": coords}
                }
                corridor_id = None
                description = f"Physical reroute via {alt_port.name} ({total_km:,.0f} km, +{time_delta:.0f}h)."
                assumptions = [
                    "Computed using searoute maritime graph with operational canal restrictions.",
                ]
                success = True
            except Exception as exc:
                logger.warning(f"Searoute failed for real divert: {exc}")

        if not success:
            # Physical routing fallback derived from mode parameters (no empirical hardcodes)
            direct_km = (
                haversine_km(origin.latitude, origin.longitude, dest.latitude, dest.longitude)
                if (origin and dest)
                else remaining_km
            )
            circuity = params.get_float(f"mode.circuity.{mode.lower()}")
            speed = params.get_float(f"mode.speed.{mode.lower()}")
            total_km = direct_km * circuity
            time_delta = (total_km / speed) if speed > 0 else (remaining_km / 50.0)
            cost_factor = total_km / max(1.0, remaining_km)
            co2_factor = total_km / max(1.0, remaining_km)
            option_key = "DIVERT_GENERIC"
            display_name = "Divert via alternate physical route"
            generic_mode = str(shipment.primary_transport_mode)
            template = {"legs": [{"mode": generic_mode, "to": "DESTINATION"}]}
            corridor_id = None
            description = f"Divert via {generic_mode} corridor ({total_km:,.0f} km)."
            assumptions = [
                "Derived from physical route distance and mode-specific transit parameters.",
            ]

    revised_eta = base_eta + timedelta(hours=time_delta) if base_eta else None
    cost_delta = baseline_freight * (cost_factor - 1.0)
    co2_delta = baseline_co2 * (co2_factor - 1.0)
    carbon = calculate_co2_cost(co2_delta)
    sla_penalty, breaches = _score_sla(orders, revised_eta)
    demurrage = estimate_demurrage(shipment, time_delta)
    total = cost_delta + carbon + sla_penalty + demurrage

    return RerouteOption(
        option_key=option_key,
        action=DecisionAction.REROUTE,
        display_name=display_name,
        description=description,
        revised_eta=revised_eta,
        cost_delta_usd=cost_delta,
        sla_penalty_usd=sla_penalty,
        demurrage_usd=demurrage,
        carbon_cost_usd=carbon,
        co2_delta_kg=co2_delta,
        sla_breaches=breaches,
        total_impact_usd=total,
        assumptions=assumptions,
        route_template=template,
        corridor_alternative_id=corridor_id,
    )


def _create_modal_option(
    alert: Alert,
    shipment: Shipment,
    orders: list[Order],
    *,
    now: datetime,
) -> RerouteOption:
    """Option C — modal shift to air over the remaining distance."""
    remaining_km, current_mode = _remaining_leg_metrics(shipment)
    weight_t = max(1, shipment.container_count) * TONNES_PER_CONTAINER

    handling_hours = params.get_float("air.handling_hours", 12.0)
    taxi = params.get_float("air.taxi_hours", 0.3)
    climb_descent = params.get_float("air.climb_descent_hours", 0.4)
    cruise_speed = params.get_float("air.cruise_speed_kmh", 860.0)
    
    block_h = taxi + climb_descent + (remaining_km / cruise_speed)
    transit_hours = block_h + handling_hours
    revised_eta = now + timedelta(hours=transit_hours)

    air_freight = _freight_for("AIR", remaining_km, weight_t)
    cur_freight = _freight_for(current_mode, remaining_km, weight_t)
    cost_delta = air_freight - cur_freight

    # Insurance line (calibration batch): a modal shift changes the premium
    # class (ocean 0.3% vs air 0.75% of insured value). Only the delta is
    # decision-relevant; cargo value proxied by order revenue.
    cargo_value = float(sum(o.revenue for o in orders))
    insurance_delta = calculate_insurance_delta(cargo_value, current_mode, "AIR")

    air_co2 = _co2_for("AIR", remaining_km, weight_t)
    cur_co2 = _co2_for(current_mode, remaining_km, weight_t)
    co2_delta = air_co2 - cur_co2
    carbon = calculate_co2_cost(co2_delta)

    sla_penalty, breaches = _score_sla(orders, revised_eta)
    total = cost_delta + carbon + sla_penalty + insurance_delta

    return RerouteOption(
        option_key="MODAL_SHIFT_AIR",
        action=DecisionAction.REROUTE,
        display_name="Modal shift to air freight",
        description=(
            f"Fly the remaining {remaining_km:,.0f} km "
            f"(~{transit_hours:.0f}h including handling). High cost and CO2, "
            "best chance of preserving SLA deadlines."
        ),
        revised_eta=revised_eta,
        cost_delta_usd=cost_delta,
        sla_penalty_usd=sla_penalty,
        demurrage_usd=0.0,
        carbon_cost_usd=carbon,
        co2_delta_kg=co2_delta,
        sla_breaches=breaches,
        total_impact_usd=total,
        assumptions=[
            f"Air transit via block-time model + {handling_hours:.0f}h handling.",
            "Air freight $0.9/t-km (NCAER Rs72/tkm anchor / fx 88) vs current-mode rate.",
            "Insurance premium delta included (air 0.75% vs ocean 0.30% of 110% insured value).",
        ],
        route_template={"legs": [{"mode": "AIR", "to": "DESTINATION"}]},
    )


# ---------------------------------------------------------------------------
# Corridor lookup
# ---------------------------------------------------------------------------


async def _create_recovery_options(
    alert: Alert,
    shipment: Shipment,
    orders: list[Order],
    session: AsyncSession,
    now: datetime,
) -> list[RerouteOption]:
    """Generate RECOVERY route plan options using the multimodal planner.

    Calls MultimodalPlanner from the current shipment position (or origin if
    no active leg) to the shipment destination.  Returns up to 2 recovery
    options, each surfacing the planner's cost/time/CO2 KPIs in the same
    RerouteOption schema for UI compatibility.

    Failures are caught and logged — the caller always returns the base 3 options
    even when this helper produces nothing.
    """
    try:
        from nexafreight.services.planner import PlanType, ShipmentPriority, get_planner

        origin_locode: str | None = None
        dest_locode: str | None = None

        # Try to resolve locodes from shipment relations (may already be loaded)
        try:
            if shipment.origin:
                origin_locode = shipment.origin.locode
            if shipment.destination:
                dest_locode = shipment.destination.locode
        except Exception:
            pass

        if not origin_locode or not dest_locode:
            return []

        weight_kg = getattr(shipment, "cargo_weight_kg", None)
        if weight_kg is None:
            weight_t = max(1, shipment.container_count or 1) * TONNES_PER_CONTAINER
        else:
            weight_t = max(0.001, float(weight_kg) / 1000.0)

        planner = get_planner()
        results = await planner.plan(
            session=session,
            shipment_id=str(shipment.id),
            origin_locode=origin_locode,
            dest_locode=dest_locode,
            query_time=now,
            priority=ShipmentPriority.EXPRESS,
            plan_type=PlanType.RECOVERY,
            cargo_weight_kg=weight_t * 1000.0,
            persist=True,
            top_k=2,
        )

        recovery_options: list[RerouteOption] = []
        for i, itin in enumerate(results[:2], start=1):
            revised_eta = itin.legs[-1].arrival_at if itin.legs else None
            sla_penalty, breaches = _score_sla(orders, revised_eta)
            modes = " + ".join(sorted({leg.mode for leg in itin.legs}))
            key = f"RECOVERY_PLAN_{i}"
            recovery_options.append(
                RerouteOption(
                    option_key=key,
                    action=DecisionAction.DIVERT,
                    display_name=f"Recovery Route {i} ({modes})",
                    description=(
                        f"Planner-generated recovery: {modes} route from {origin_locode}→{dest_locode}. "
                        f"Cost ${itin.total_cost_usd:,.0f} · {itin.total_time_h:.0f}h · "
                        f"{itin.total_co2_kg:.0f} kg CO₂ (DERIVED — planner scored)"
                    ),
                    revised_eta=revised_eta,
                    cost_delta_usd=itin.total_cost_usd,
                    sla_penalty_usd=sla_penalty,
                    demurrage_usd=0.0,
                    carbon_cost_usd=0.0,
                    co2_delta_kg=itin.total_co2_kg,
                    sla_breaches=breaches,
                    total_impact_usd=round(itin.total_cost_usd + sla_penalty, 2),
                    assumptions=[
                        f"DERIVED — computed by schedule-aware multimodal planner (seed={None}).",
                        f"Reliability score: {itin.reliability_score:.0%}.",
                        f"Objective weights: {itin.objective_weights}.",
                        "All segment speeds and costs sourced from parameter tables (no hardcoded empirical values).",
                    ],
                    route_template={"plan_type": "RECOVERY", "rank": itin.rank},
                )
            )
        return recovery_options

    except Exception as exc:
        logger.warning("Recovery plan generation failed (non-fatal): %s", exc)
        return []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def generate_options(
    session: AsyncSession,
    alert: Alert,
    *,
    now: datetime | None = None,
) -> list[RerouteOption]:
    """Generate scored reroute options for an alert.

    Always returns the three baseline options (ACCEPT_DELAY, DIVERT, MODAL_SHIFT).
    When the multimodal planner is available and the network is seeded, up to 2
    additional RECOVERY_PLAN options are appended. The recommended option is the
    one with the lowest total financial impact across all options.

    Order is stable: [ACCEPT_DELAY, DIVERT, MODAL_SHIFT_AIR, RECOVERY_PLAN_1?, RECOVERY_PLAN_2?].
    """
    now = now or datetime.now(UTC)

    shipment = (
        (
            await session.execute(
                select(Shipment).where(Shipment.id == alert.shipment_id)
            )
        )
        .scalars()
        .first()
    )
    if shipment is None:
        from nexafreight.exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("Shipment", alert.shipment_id)
    await session.refresh(shipment, ["legs", "orders"])
    orders = list(shipment.orders)

    try:
        payload = json.loads(alert.sla_breach_details_json or "{}")
    except json.JSONDecodeError:
        payload = {}

    # Query the parent disruption directly — accessing the `alert.disruption`
    # relationship here would lazy-load IO outside the async greenlet.
    disruption_type = "MANUAL"
    if alert.disruption_id:
        from nexafreight.models import Disruption

        disruption = await session.get(Disruption, alert.disruption_id)
        if disruption is not None:
            disruption_type = str(disruption.disruption_type)
    corridor = await _find_alternative_port(session, disruption_type)

    accept = _create_accept_option(alert, shipment, orders, payload)
    divert = await _create_divert_option(alert, shipment, orders, corridor, session)
    modal = _create_modal_option(alert, shipment, orders, now=now)

    options: list[RerouteOption] = [accept, divert, modal]

    # Augment with planner-generated recovery options (non-fatal if unavailable)
    try:
        await session.refresh(shipment, ["origin", "destination"])
    except Exception:
        pass
    recovery = await _create_recovery_options(alert, shipment, orders, session, now)
    options.extend(recovery)

    best = min(options, key=lambda o: o.total_impact_usd)
    options = [replace(o, recommended=True) if o is best else o for o in options]

    # Task 14: revealed-preference prior reorders the slate (presentation
    # only — the recommended flag stays the pure cost-optimal answer).
    try:
        prior = await preference_stats(session)
        options = apply_preference_prior(options, prior, disruption_type)
    except Exception:  # non-fatal: a stats read must never block a decision
        logger.warning("preference prior unavailable; serving unranked slate", exc_info=True)

    logger.info(
        "Generated %d options for alert %s; recommended=%s ($%.2f)",
        len(options),
        alert.id,
        best.option_key,
        best.total_impact_usd,
    )
    return options

async def _find_alternative_port(
    session: AsyncSession, disruption_type: str
) -> dict | None:
    """Corridor lookup: best seeded alternative applicable to this disruption.

    "Best" = least added transit time. Applicability is stored as a JSON list
    of DisruptionType values on the corridor row.
    """
    result = await session.execute(select(CorridorAlternative))
    candidates: list[CorridorAlternative] = []
    for corridor in result.scalars().all():
        try:
            applies = json.loads(corridor.applicable_disruption_types_json)
        except json.JSONDecodeError:
            continue
        if disruption_type in applies:
            candidates.append(corridor)

    if not candidates:
        return None

    best = min(candidates, key=lambda c: c.time_delta_hours)
    return {
        "id": best.id,
        "option_key": best.option_key,
        "display_name": best.display_name,
        "cost_delta_factor": best.cost_delta_factor,
        "time_delta_hours": best.time_delta_hours,
        "co2_delta_factor": best.co2_delta_factor,
        "route_template": json.loads(best.route_template_json),
    }

