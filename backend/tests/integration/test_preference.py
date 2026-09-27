"""Task 14: preference stats from decision_outcomes + slate reordering."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from nexafreight.enums import (
    AlertSeverity,
    AlertStatus,
    DecisionAction,
    DisruptionStatus,
)
from nexafreight.models import (
    Alert,
    Decision,
    DecisionOutcome,
    Disruption,
)
from nexafreight.services.preference import (
    apply_preference_prior,
    cost_band,
    preference_stats,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_cost_band_edges() -> None:
    assert cost_band(-10.0) == "nonpositive"
    assert cost_band(0.0) == "nonpositive"
    assert cost_band(999.99) == "low"
    assert cost_band(1000.0) == "low"
    assert cost_band(10_000.0) == "mid"
    assert cost_band(10_001.0) == "high"


def _option(option_key: str, total: float, recommended: bool = False):
    from dataclasses import replace

    from nexafreight.services.reroute_engine import RerouteOption

    base = RerouteOption(
        option_key=option_key,
        action=DecisionAction.ACCEPT_DELAY,
        display_name=option_key,
        description="x",
        revised_eta=None,
        cost_delta_usd=0.0,
        sla_penalty_usd=0.0,
        demurrage_usd=0.0,
        carbon_cost_usd=0.0,
        co2_delta_kg=0.0,
        sla_breaches=0,
        total_impact_usd=total,
        recommended=recommended,
    )
    return base


def test_apply_prior_demotes_zero_acceptance_and_keeps_flag() -> None:
    stats = {
        ("PORT_CONGESTION", "nonpositive"): {"DIVERT_GENERIC": 4},
    }
    options = [
        _option("ACCEPT_DELAY", 0.0, recommended=True),
        _option("DIVERT_GENERIC", -406.0),
        _option("MODAL_SHIFT_AIR", 12_000.0),
    ]
    out = apply_preference_prior(options, stats, "PORT_CONGESTION")
    assert [o.option_key for o in out] == ["DIVERT_GENERIC", "MODAL_SHIFT_AIR", "ACCEPT_DELAY"]
    # the recommended flag rides with its option, untouched
    assert out[2].recommended is True
    # demotion is annotated
    assert "0/4 historical acceptance" in out[2].assumptions[-1]
    # cold start: no rows for this disruption type -> untouched
    assert [o.option_key for o in apply_preference_prior(options, {}, "WEATHER")] == [
        "ACCEPT_DELAY",
        "DIVERT_GENERIC",
        "MODAL_SHIFT_AIR",
    ]


async def test_preference_stats_joins_the_chain(
    db_session, make_shipment, make_location, seed_admin_user
) -> None:
    from nexafreight.models import Location

    dest = await make_location(locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.92, longitude=4.48)
    origin = await make_location(locode="INJNP", name="JNPT", country_code="IN", latitude=18.95, longitude=72.95)
    shipment = await make_shipment(
        origin=origin, destination=dest, status="IN_TRANSIT", route_version=1
    )

    async def _seed_history(n: int, chosen: str, predicted: float) -> None:
        for _ in range(n):
            disruption = Disruption(
                shipment_id=shipment.id,
                disruption_type="PORT_CONGESTION",
                status=DisruptionStatus.RESOLVED.value,
                description="history",
                detected_at=NOW,
            )
            db_session.add(disruption)
            await db_session.flush()
            alert = Alert(
                disruption_id=disruption.id,
                shipment_id=shipment.id,
                severity=AlertSeverity.LOW,
                status=AlertStatus.RESOLVED,
                financial_exposure=0.0,
                sla_breach_details_json=json.dumps({}),
            )
            db_session.add(alert)
            await db_session.flush()
            decision = Decision(
                alert_id=alert.id,
                shipment_id=shipment.id,
                action=DecisionAction.REROUTE,
                chosen_option_key=chosen,
                options_snapshot_json=json.dumps([]),
                financial_impact=predicted,
                route_version_before=1,
                route_version_after=1,
                approved_by=seed_admin_user.id,
            )
            db_session.add(decision)
            await db_session.flush()
            db_session.add(
                DecisionOutcome(
                    decision_id=decision.id,
                    shipment_id=shipment.id,
                    chosen_option_key=chosen,
                    predicted_total_impact_usd=predicted,
                )
            )
            await db_session.flush()

    await _seed_history(4, "DIVERT_GENERIC", -406.0)

    stats = await preference_stats(db_session)
    assert stats[("PORT_CONGESTION", "nonpositive")] == {"DIVERT_GENERIC": 4}


async def test_generate_options_applies_prior_end_to_end(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    """4x DIVERT chosen in the nonpositive band -> ACCEPT_DELAY falls last."""
    from tests.integration.test_decision_outcome import _jam_world
    from nexafreight.services.reroute_engine import generate_options

    fx = await _jam_world(db_session, make_shipment, make_order, make_leg, make_location)
    shipment = fx["shipment"]

    # Historical slate: four PORT_CONGESTION decisions, DIVERT chosen with a
    # NEGATIVE predicted impact (real: the day-6 walk had -$406.07) -> same
    # "nonpositive" band as ACCEPT_DELAY's $0. One disruption+alert pair per
    # historical decision (alerts.disruption_id is UNIQUE).
    shipment2 = shipment
    for _ in range(4):
        d = Disruption(
            shipment_id=shipment2.id,
            disruption_type="PORT_CONGESTION",
            status=DisruptionStatus.RESOLVED.value,
            description="history",
            detected_at=NOW,
        )
        db_session.add(d)
        await db_session.flush()
        a = Alert(
            disruption_id=d.id,
            shipment_id=shipment2.id,
            severity=AlertSeverity.LOW,
            status=AlertStatus.RESOLVED,
            financial_exposure=0.0,
            sla_breach_details_json=json.dumps({}),
        )
        db_session.add(a)
        await db_session.flush()
        dec = Decision(
            alert_id=a.id,
            shipment_id=shipment2.id,
            action=DecisionAction.REROUTE,
            chosen_option_key="DIVERT_GENERIC",
            options_snapshot_json=json.dumps([]),
            financial_impact=-406.07,
            route_version_before=1,
            route_version_after=1,
            approved_by=seed_admin_user.id,
        )
        db_session.add(dec)
        await db_session.flush()
        db_session.add(
            DecisionOutcome(
                decision_id=dec.id,
                shipment_id=shipment2.id,
                chosen_option_key="DIVERT_GENERIC",
                predicted_total_impact_usd=-406.07,
            )
        )
    await db_session.flush()

    options = await generate_options(db_session, fx["alert"], now=NOW)
    keys = [o.option_key for o in options]
    assert "DIVERT_GENERIC" in keys and "ACCEPT_DELAY" in keys
    # ACCEPT_DELAY has 0/4 acceptance in its band -> demoted below DIVERT
    assert keys.index("ACCEPT_DELAY") > keys.index("DIVERT_GENERIC")
    # exactly one recommended, and it is still the pure cost-optimal option
    rec = [o for o in options if o.recommended]
    assert len(rec) == 1
    assert rec[0].total_impact_usd == min(o.total_impact_usd for o in options)
