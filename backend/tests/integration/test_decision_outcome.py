"""Task 12: DecisionOutcome phase 1 (predicted freeze on approval) and
phase 2 (realized backfill once the shipment is DELIVERED)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from nexafreight.enums import AlertSeverity, AlertStatus, LegStatus, TransportMode
from nexafreight.models import (
    Alert,
    Decision,
    DecisionOutcome,
    Disruption,
    Shipment,
)
from nexafreight.services.decision_executor import execute_decision
from nexafreight.services.decision_outcome import finalize_decision_outcomes

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _jam_world(
    db_session, make_shipment, make_order, make_leg, make_location
) -> dict:
    """Minimal port-congestion alert world (mirrors test_decision_executor)."""
    from nexafreight.models import CorridorAlternative

    origin = await make_location(
        locode="INJNP", name="JNPT", country_code="IN", latitude=18.95, longitude=72.95
    )
    dest = await make_location(
        locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.9225, longitude=4.479
    )
    shipment = await make_shipment(
        origin=origin,
        destination=dest,
        status="IN_TRANSIT",
        primary_transport_mode=TransportMode.SEA,
        container_count=2,
        route_version=1,
    )
    replaced = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        mode=TransportMode.SEA,
        status=LegStatus.IN_PROGRESS,
        origin=origin,
        destination=dest,
        planned_departure=NOW - timedelta(days=2),
        planned_arrival=NOW + timedelta(days=10),
    )
    order = await make_order(
        order_number="ORD-OUTCOME-1",
        shipment=shipment,
        revenue=20_000.0,
        shipping_cost=1_500.0,
        sla_deadline=NOW + timedelta(days=12),
    )
    disruption = Disruption(
        shipment_id=shipment.id,
        disruption_type="PORT_CONGESTION",
        status="ACTIVE",
        description="congestion",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()
    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        financial_exposure=2_000.0,
        sla_breach_details_json=json.dumps(
            {"estimated_delay_hours": 40.0, "breaches": [], "revised_eta": None}
        ),
    )
    db_session.add(alert)
    await db_session.flush()
    return {
        "shipment": shipment,
        "order": order,
        "alert": alert,
        "replaced": replaced,
    }


@pytest.mark.asyncio
async def test_outcome_frozen_on_approval_with_override(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _jam_world(db_session, make_shipment, make_order, make_leg, make_location)
    operator = seed_admin_user

    decision = await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=operator, now=NOW
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(DecisionOutcome).where(DecisionOutcome.decision_id == decision.id)
        )
    ).scalar_one()
    assert row.chosen_option_key == "ACCEPT_DELAY"
    assert row.predicted_total_impact_usd == 0.0  # ACCEPT is the $0 baseline
    assert row.predicted_cost_delta_usd == 0.0
    assert row.override_reason is None  # ACCEPT is recommended on low exposure


@pytest.mark.asyncio
async def test_override_reason_when_operator_picks_non_recommended(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _jam_world(db_session, make_shipment, make_order, make_leg, make_location)
    operator = seed_admin_user

    decision = await execute_decision(
        db_session,
        alert_id=fx["alert"].id,
        option_key="MODAL_SHIFT_AIR",
        user=operator,
        now=NOW,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(DecisionOutcome).where(DecisionOutcome.decision_id == decision.id)
        )
    ).scalar_one()
    assert row.chosen_option_key == "MODAL_SHIFT_AIR"
    assert row.recommended_option_key in ("ACCEPT_DELAY", "DIVERT_GENERIC")
    assert row.chosen_option_key != row.recommended_option_key
    assert row.override_reason is not None
    assert "MODAL_SHIFT_AIR" in row.override_reason
    assert row.predicted_total_impact_usd > 0.0
    assert row.realized_arrival_delta_h is None  # phase 2 pending


@pytest.mark.asyncio
async def test_finalizer_computes_realized_once_delivered(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    from nexafreight.enums import ShipmentStatus

    fx = await _jam_world(db_session, make_shipment, make_order, make_leg, make_location)
    operator = seed_admin_user
    decision = await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=operator, now=NOW
    )
    await db_session.flush()

    shipment = fx["shipment"]
    # The replaced plan arrives NOW+10d; reality delivered NOW+10d+30h (30h late
    # vs the replaced plan, still 18h before the order's SLA deadline NOW+12d).
    delivered_at = NOW + timedelta(days=10, hours=30)
    delivered_leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=2,
        mode=TransportMode.SEA,
        status=LegStatus.COMPLETED,
        origin=fx["shipment"].origin,
        destination=fx["shipment"].destination,
        planned_departure=NOW + timedelta(hours=1),
        planned_arrival=delivered_at,
    )
    delivered_leg.actual_arrival = delivered_at
    shipment.status = ShipmentStatus.DELIVERED
    shipment.route_version = 1
    await db_session.flush()

    finalized = await finalize_decision_outcomes(db_session)
    assert decision.id in [fid for fid in finalized] or len(finalized) == 1

    row = (
        await db_session.execute(
            select(DecisionOutcome).where(DecisionOutcome.decision_id == decision.id)
        )
    ).scalar_one()
    assert row.realized_arrival_delta_h == pytest.approx(30.0, abs=0.01)
    # 30h late vs the replaced plan, but the SLA deadline is NOW+12d = 18h
    # after actual arrival -> no penalty.
    assert row.realized_penalty_usd == 0.0
    assert row.outcome_finalized_at is not None

    # Idempotent: second run finalizes nothing new.
    again = await finalize_decision_outcomes(db_session)
    assert again == []


@pytest.mark.asyncio
async def test_finalizer_flags_sla_penalty_when_actually_late(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    from nexafreight.enums import ShipmentStatus

    fx = await _jam_world(db_session, make_shipment, make_order, make_leg, make_location)
    operator = seed_admin_user
    decision = await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=operator, now=NOW
    )
    await db_session.flush()

    shipment = fx["shipment"]
    # Arrive 8 days late vs the replaced plan -> 6 days past the SLA deadline
    # (NOW+12d) -> ceil(6/7) = 1 part-week -> 0.5% of 20k = $100.
    delivered_at = NOW + timedelta(days=18)
    delivered_leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=2,
        mode=TransportMode.SEA,
        status=LegStatus.COMPLETED,
        origin=shipment.origin,
        destination=shipment.destination,
        planned_departure=NOW + timedelta(hours=1),
        planned_arrival=delivered_at,
    )
    delivered_leg.actual_arrival = delivered_at
    shipment.status = ShipmentStatus.DELIVERED
    await db_session.flush()

    await finalize_decision_outcomes(db_session)
    row = (
        await db_session.execute(
            select(DecisionOutcome).where(DecisionOutcome.decision_id == decision.id)
        )
    ).scalar_one()
    assert row.realized_arrival_delta_h == pytest.approx(8 * 24.0, abs=0.01)
    assert row.realized_penalty_usd == pytest.approx(100.0, abs=0.01)
