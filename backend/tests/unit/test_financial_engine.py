"""Unit tests for financial impact calculation engine.

Tests use exact known numeric values, not just structural assertions,
to establish baseline correctness that later ML/rerouting tasks will
trust without re-verifying the math.

Definitive Plan Phase 1 rules:
- SLA penalty: revenue × rate × days, capped at 10% of revenue
- Demurrage: tiered after free days (tier-1 flat, tier-2 doubled)
"""

from __future__ import annotations

import pytest

from nexafreight.services.financial_engine import (
    CARBON_COST_PER_KG,
    OrderFinancialInput,
    assess_order_margin,
    calculate_carbon_cost,
    calculate_co2_cost,
    calculate_co2_kg,
    calculate_demurrage,
    calculate_freight_cost,
    calculate_order_financial_impact,
    calculate_shipment_financial_impact,
    calculate_sla_penalty,
    calculate_sla_penalty_weekly,
    generate_pnl_snapshot,
)
from nexafreight.services.insurance import (
    INSURED_VALUE_UPLIFT,
    INSURANCE_PCT_BY_MODE,
    calculate_insurance_delta,
    calculate_insurance_premium,
)


def test_calculate_sla_penalty_zero_days_late() -> None:
    """No penalty when delivery is on time or early."""
    result = calculate_sla_penalty(revenue=10000.0, penalty_pct=0.05, days_late=0)
    assert result == 0.0

    result_early = calculate_sla_penalty(revenue=10000.0, penalty_pct=0.05, days_late=-3)
    assert result_early == 0.0


def test_calculate_sla_penalty_positive_days_late() -> None:
    """Penalty = revenue × rate × day, under the 10% cap (1 day late = 5%)."""
    # Arithmetic: 20000 * 0.05 * 1 = 1000.0 (below the 10% cap of 2000)
    result = calculate_sla_penalty(revenue=20000.0, penalty_pct=0.05, days_late=1)
    assert result == 1000.0


def test_calculate_sla_penalty_capped_at_10pct() -> None:
    """SLA penalty is capped at 10% of revenue (Plan Phase 1)."""
    # Uncapped would be 50000 * 0.10 * 7 = 35000; cap is 50000 * 0.10 = 5000
    result = calculate_sla_penalty(revenue=50000.0, penalty_pct=0.10, days_late=7)
    assert result == 5000.0


def test_calculate_sla_penalty_cap_boundary() -> None:
    """One day below the cap stays uncapped; one day past hits the cap."""
    # 20000 * 0.05 * 2 = 2000 == cap exactly at 10%
    assert calculate_sla_penalty(20000.0, 0.05, 2) == 2000.0
    # 20000 * 0.05 * 3 = 3000 > 2000 cap
    assert calculate_sla_penalty(20000.0, 0.05, 3) == 2000.0


def test_calculate_sla_penalty_weekly_ld_norms() -> None:
    """Weekly LD norms: 0.5%/week, any part-week rounds up, cap 10%."""
    pct, cap = 0.005, 0.10
    # 6 days late -> 1 week: 20000 * 0.005 * 1 = 100
    assert calculate_sla_penalty_weekly(20000.0, pct, 6, cap_pct=cap) == 100.0
    # 8 days late -> 2 weeks (round up): 20000 * 0.005 * 2 = 200
    assert calculate_sla_penalty_weekly(20000.0, pct, 8, cap_pct=cap) == 200.0
    # 140 days late -> 20 weeks: uncapped 2000 == 10% cap of 2000 exactly
    assert calculate_sla_penalty_weekly(20000.0, pct, 140, cap_pct=cap) == 2000.0
    # 141 days -> 21 weeks: uncapped 2100 > cap
    assert calculate_sla_penalty_weekly(20000.0, pct, 141, cap_pct=cap) == 2000.0
    # on time / early
    assert calculate_sla_penalty_weekly(20000.0, pct, 0, cap_pct=cap) == 0.0
    assert calculate_sla_penalty_weekly(20000.0, pct, -5, cap_pct=cap) == 0.0


def test_insurance_premium_by_mode() -> None:
    """Premium = cargo value x 110% uplift x mode pct (ocean 0.3%, air 0.75%)."""
    # SEA: 10000 * 1.10 * 0.003 = 33.0
    assert calculate_insurance_premium(10_000.0, "SEA") == pytest.approx(33.0)
    # AIR: 10000 * 1.10 * 0.0075 = 82.5
    assert calculate_insurance_premium(10_000.0, "AIR") == pytest.approx(82.5)
    # ROAD: 10000 * 1.10 * 0.005 = 55.0
    assert calculate_insurance_premium(10_000.0, "ROAD") == pytest.approx(55.0)
    # RAIL shares the road rate (documented, no separate public anchor)
    assert calculate_insurance_premium(10_000.0, "RAIL") == pytest.approx(55.0)
    # TransportMode enum accepted
    assert calculate_insurance_premium(10_000.0, "SEA") == calculate_insurance_premium(10_000.0, "SEA")


def test_insurance_delta_only_charges_the_difference() -> None:
    """Modal shift decision uses the premium DELTA, not the full premium."""
    # SEA -> AIR: 10000 * 1.10 * (0.0075 - 0.003) = 49.5
    assert calculate_insurance_delta(10_000.0, "SEA", "AIR") == pytest.approx(49.5)
    # same mode: no delta
    assert calculate_insurance_delta(10_000.0, "SEA", "SEA") == 0.0
    # reverse shift refunds the premium class difference
    assert calculate_insurance_delta(10_000.0, "AIR", "SEA") == pytest.approx(-49.5)


def test_insurance_constants_match_registry_anchors() -> None:
    """Module constants mirror the params registry defaults (Reg. doc SS8)."""
    from nexafreight.core.params import FALLBACK_DEFAULTS

    assert INSURANCE_PCT_BY_MODE["SEA"] == FALLBACK_DEFAULTS["insurance.pct_of_value.sea"]
    assert INSURANCE_PCT_BY_MODE["AIR"] == FALLBACK_DEFAULTS["insurance.pct_of_value.air"]
    assert INSURANCE_PCT_BY_MODE["ROAD"] == FALLBACK_DEFAULTS["insurance.pct_of_value.road"]
    assert INSURED_VALUE_UPLIFT == FALLBACK_DEFAULTS["insurance.insured_value_uplift"]


def test_demurrage_within_free_days() -> None:
    """No demurrage when within free days."""
    result = calculate_demurrage(extra_days=2, free_days=5, daily_rate=100.0)
    assert result == 0.0

    result_boundary = calculate_demurrage(extra_days=5, free_days=5, daily_rate=100.0)
    assert result_boundary == 0.0


def test_calculate_demurrage_beyond_free_days() -> None:
    """Tier-1 rate applies for the first 7 billable days."""
    # Arithmetic: (10 - 3) * 50.0 = 350.0
    result = calculate_demurrage(extra_days=10, free_days=3, daily_rate=50.0)
    assert result == 350.0

    # Arithmetic: (8 - 5) * 200.0 = 600.0
    result_higher_rate = calculate_demurrage(extra_days=8, free_days=5, daily_rate=200.0)
    assert result_higher_rate == 600.0


def test_calculate_demurrage_tier2_steepening() -> None:
    """Beyond 7 billable days the rate doubles (tiered per the plan)."""
    # billable = 9 → 7 * 150 + 2 * 150 * 2 = 1050 + 600 = 1650
    result = calculate_demurrage(extra_days=13, free_days=4, daily_rate=150.0)
    assert result == 1650.0


def test_calculate_carbon_cost_positive_delta() -> None:
    """Positive CO2 delta produces positive cost (increase)."""
    result = calculate_carbon_cost(co2_delta_kg=1000.0, cost_per_kg=0.08)
    assert result == 80.0


def test_calculate_carbon_cost_custom_rate() -> None:
    """Custom cost_per_kg scales result correctly."""
    result = calculate_carbon_cost(co2_delta_kg=500.0, cost_per_kg=0.12)
    assert result == 60.0


def test_calculate_carbon_cost_negative_delta() -> None:
    """Negative CO2 delta (improvement) produces negative cost (savings)."""
    result = calculate_carbon_cost(co2_delta_kg=-200.0, cost_per_kg=0.08)
    assert result == -16.0


def test_calculate_freight_cost_by_mode() -> None:
    """Nominal freight cost = rate × distance × weight, per mode."""
    # AIR: 0.9 × 5000 × 28 = 126000  (NCAER Rs72/tkm anchor / fx 88)
    assert calculate_freight_cost(5000.0, 28.0, "AIR") == 126_000.0
    # SEA: 0.012 × 5000 × 28 = 1680  (mainline INDUSTRY anchor)
    assert calculate_freight_cost(5000.0, 28.0, "SEA") == 1_680.0
    # ROAD: 0.0334 × 5000 × 28 = 4676  (Rs3.2/tkm bottom-up / fx 95.8)
    assert calculate_freight_cost(5000.0, 28.0, "ROAD") == 4_676.0
    # RAIL: 0.0146 × 5000 × 28 = 2044  (Rs1.4/tkm class-avg / fx 95.8)
    assert calculate_freight_cost(5000.0, 28.0, "RAIL") == 2_044.0
    # Unknown mode falls back to SEA rate
    assert calculate_freight_cost(5000.0, 28.0, "DRONE") == 1_680.0


def test_calculate_co2_kg_by_mode() -> None:
    """kg CO2 = g/t-km × km × t / 1000."""
    # AIR: 500 × 5000 × 28 / 1000 = 70000 kg
    assert calculate_co2_kg(5000.0, 28.0, "AIR") == 70_000.0
    # SEA: 8.0 × 5000 × 28 / 1000 = 1120 kg (GLEC band mid)
    assert calculate_co2_kg(5000.0, 28.0, "SEA") == 1_120.0


def test_calculate_co2_cost_uses_carbon_price() -> None:
    """Carbon price is $0.08/kg."""
    assert CARBON_COST_PER_KG == 0.08
    assert calculate_co2_cost(1_120.0) == pytest.approx(89.6)


def test_calculate_order_financial_impact_full_scenario() -> None:
    """Full order impact calculation with all components."""
    order_input = OrderFinancialInput(
        revenue=20000.0,
        penalty_pct=0.05,
        days_late=2,  # SLA penalty: 20000 * 0.05 * 2 = 2000.0 (== cap boundary)
        extra_days=7,
        free_days=3,
        daily_rate=100.0,  # Demurrage: (7-3) * 100 = 400.0
        co2_delta_kg=500.0,  # Carbon: 500 * 0.08 = 40.0
    )

    result = calculate_order_financial_impact(order_input)

    assert result.sla_penalty == 2000.0
    assert result.demurrage == 400.0
    assert result.carbon_cost == 40.0
    assert result.total_impact_usd == 2440.0


def test_calculate_shipment_financial_impact_multi_order() -> None:
    """Multi-order shipment aggregation, capped SLA penalties."""
    orders = [
        # Order 1: SLA 10000 * 0.05 * 3 = 1500 (under 1000 cap? no → cap=1000 → capped)
        OrderFinancialInput(
            revenue=10000.0,
            penalty_pct=0.05,
            days_late=3,  # SLA: min(1500, 1000) = 1000.0
            extra_days=5,
            free_days=2,
            daily_rate=50.0,  # Demurrage: (5-2) * 50 = 150.0
            co2_delta_kg=200.0,  # Carbon: 16.0
        ),  # Total: 1166.0
        # Order 2: On time, no demurrage
        OrderFinancialInput(
            revenue=5000.0,
            penalty_pct=0.05,
            days_late=0,  # SLA: 0.0
            extra_days=1,
            free_days=3,
            daily_rate=50.0,  # Demurrage: 0.0
            co2_delta_kg=100.0,  # Carbon: 8.0
        ),  # Total: 8.0
        # Order 3: Very late → SLA capped at 10%
        OrderFinancialInput(
            revenue=30000.0,
            penalty_pct=0.10,
            days_late=5,  # SLA: min(15000, 3000) = 3000.0
            extra_days=10,
            free_days=3,
            daily_rate=200.0,  # Demurrage: tier1 → (10-3) * 200 = 1400.0
            co2_delta_kg=1000.0,  # Carbon: 80.0
        ),  # Total: 4480.0
    ]

    result = calculate_shipment_financial_impact(orders)

    assert result.per_order_impacts[0].total_impact_usd == 1166.0
    assert result.per_order_impacts[1].total_impact_usd == 8.0
    assert result.per_order_impacts[2].total_impact_usd == 4480.0
    # Total: 1166 + 8 + 4480 = 5654.0
    assert result.total_impact_usd == 5654.0


def test_split_reroute_savings_scenario() -> None:
    """Comparing two routing scenarios produces correct net savings."""
    # Scenario A: Stay on current slow route (SLA penalties capped)
    current_route_orders = [
        OrderFinancialInput(
            revenue=10000.0,
            penalty_pct=0.05,
            days_late=5,  # SLA: min(2500, 1000) = 1000.0
            extra_days=8,
            free_days=3,
            daily_rate=100.0,  # tier1 → (8-3) * 100 = 500.0
            co2_delta_kg=0.0,
        ),  # Total: 1500.0
        OrderFinancialInput(
            revenue=15000.0,
            penalty_pct=0.05,
            days_late=5,  # SLA: min(3750, 1500) = 1500.0
            extra_days=8,
            free_days=3,
            daily_rate=100.0,  # 500.0
            co2_delta_kg=0.0,
        ),  # Total: 2000.0
    ]
    current_route_impact = calculate_shipment_financial_impact(current_route_orders)
    assert current_route_impact.total_impact_usd == 3500.0

    # Scenario B: Reroute high-priority order via air
    reroute_orders = [
        OrderFinancialInput(
            revenue=10000.0,
            penalty_pct=0.05,
            days_late=5,
            extra_days=8,
            free_days=3,
            daily_rate=100.0,
            co2_delta_kg=0.0,  # Total: 1500.0 (unchanged)
        ),
        OrderFinancialInput(
            revenue=15000.0,
            penalty_pct=0.05,
            days_late=0,  # SLA: 0.0 (on time via air)
            extra_days=0,
            free_days=3,
            daily_rate=100.0,
            co2_delta_kg=800.0,  # Carbon: 64.0
        ),  # Total: 64.0
    ]
    reroute_impact = calculate_shipment_financial_impact(reroute_orders)
    assert reroute_impact.total_impact_usd == 1564.0

    # Net savings: 3500 - 1564 = 1936.0
    net_savings = current_route_impact.total_impact_usd - reroute_impact.total_impact_usd
    assert net_savings == 1936.0


def test_generate_pnl_snapshot_margin_math() -> None:
    """PnL: total_costs sum, margin = revenue − costs, margin% normalised."""
    pnl = generate_pnl_snapshot(
        revenue_usd=10_000.0,
        shipping_cost_usd=1_000.0,
        sla_penalty_usd=500.0,
        demurrage_usd=250.0,
        freight_cost_usd=2_800.0,
        carbon_cost_usd=72.8,
    )
    assert pnl.total_costs_usd == pytest.approx(4622.8)
    assert pnl.margin_usd == pytest.approx(5377.2)
    assert pnl.margin_pct == pytest.approx(0.53772)
    assert any("penalties" in w for w in pnl.warnings)  # flags warn about penalties
    # No revenue → margin_pct undefined, warns
    pnl_no_rev = generate_pnl_snapshot(
        revenue_usd=0.0,
        shipping_cost_usd=100.0,
        sla_penalty_usd=0.0,
        demurrage_usd=0.0,
        freight_cost_usd=0.0,
        carbon_cost_usd=0.0,
    )
    assert pnl_no_rev.margin_pct is None
    assert pnl_no_rev.margin_usd == -100.0
    assert any("No revenue" in w for w in pnl_no_rev.warnings)


def test_generate_pnl_snapshot_negative_margin_warns() -> None:
    pnl = generate_pnl_snapshot(
        revenue_usd=1_000.0,
        shipping_cost_usd=2_000.0,
        sla_penalty_usd=0.0,
        demurrage_usd=0.0,
        freight_cost_usd=0.0,
        carbon_cost_usd=0.0,
    )
    assert pnl.margin_usd == -1000.0
    assert any("negative margin" in w for w in pnl.warnings)


def test_assess_order_margin_bands() -> None:
    go = assess_order_margin(
        revenue_usd=10_000.0,
        shipping_cost_usd=1_000.0,
        sla_penalty_usd=0.0,
        demurrage_usd=0.0,
        freight_cost_usd=1_000.0,
        carbon_cost_usd=50.0,
    )
    assert go.startswith("GO")
    nogo = assess_order_margin(
        revenue_usd=1_000.0,
        shipping_cost_usd=2_000.0,
        sla_penalty_usd=0.0,
        demurrage_usd=0.0,
        freight_cost_usd=0.0,
        carbon_cost_usd=0.0,
    )
    assert nogo.startswith("NO-GO")
