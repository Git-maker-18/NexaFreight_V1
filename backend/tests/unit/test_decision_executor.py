"""Unit tests for the decision executor (Definitive Plan — Phase 6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import AlertSeverity, AlertStatus, LegStatus, TransportMode
from nexafreight.exceptions import (
    ConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from nexafreight.models import Alert, AuditLog, CorridorAlternative, Disruption, Leg
from nexafreight.services.decision_executor import (
    execute_decision,
    get_mode_speed,
    haversine_km,
)


NOW = datetime.now(UTC)


def test_haversine_nyc_london() -> None:
    """NYC → London great-circle ≈ 5567 km (±1%)."""
    dist = haversine_km(40.7128, -74.006, 51.5074, -0.1278)
    assert 5510 < dist < 5625


async def _world(
    db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user
):
    """Shipment mid-sea with 2 PLANNED remaining legs; corridor seeded."""
    nyc = await make_location(locode="USNYC", name="New York", latitude=40.7128, longitude=-74.006)
    piraeus = await make_location(
        locode="GRPIR", name="Piraeus", country_code="GR", latitude=37.94, longitude=23.64
    )
    rotterdam = await make_location(
        locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.9225, longitude=4.479
    )
    shipment = await make_shipment(
        origin=nyc,
        destination=rotterdam,
        status="IN_TRANSIT",
        primary_transport_mode=TransportMode.SEA,
        container_count=2,
        route_version=1,
    )
    leg1 = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        mode=TransportMode.SEA,
        status=LegStatus.IN_PROGRESS,
        origin=nyc,
        destination=piraeus,
        planned_departure=NOW - timedelta(days=2),
        planned_arrival=NOW + timedelta(days=4),
    )
    leg1.distance_km = 2500.0
    leg2 = await make_leg(
        shipment_id=shipment.id,
        sequence_number=2,
        mode=TransportMode.SEA,
        status=LegStatus.PLANNED,
        origin=nyc,
        destination=rotterdam,
        planned_departure=NOW + timedelta(days=4),
        planned_arrival=NOW + timedelta(days=11, hours=6),
    )
    leg2.distance_km = 5000.0

    order = await make_order(
        order_number="ORD-EXEC-1",
        shipment=shipment,
        revenue=20_000.0,
        shipping_cost=1_500.0,
        sla_deadline=NOW + timedelta(days=11, hours=6),
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
            {"estimated_delay_hours": 50.0, "breaches": [], "revised_eta": None}
        ),
    )
    db_session.add(alert)
    await db_session.flush()

    corridor = CorridorAlternative(
        option_key="VIA_PIRAEUS",
        display_name="Divert via Piraeus",
        applicable_disruption_types_json=json.dumps(["PORT_CONGESTION"]),
        route_template_json=json.dumps({"legs": [{"mode": "SEA", "to": "DESTINATION"}]}),
        cost_delta_factor=1.2,
        time_delta_hours=30.0,
        co2_delta_factor=1.1,
    )
    db_session.add(corridor)
    await db_session.commit()
    await db_session.refresh(alert, ["disruption"])
    return {
        "shipment": shipment,
        "order": order,
        "alert": alert,
        "leg2": leg2,
        "user": seed_admin_user,
    }


async def test_execute_accept_delay_no_leg_rewrites(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _world(db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user)
    decision = await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=fx["user"], now=NOW
    )
    await db_session.commit()

    assert str(decision.action) == "ACCEPT_DELAY"
    assert decision.route_version_before == 1
    assert decision.route_version_after == 1  # no reroute
    # Planned leg stays PLANNED (nothing replaced)
    await db_session.refresh(fx["leg2"])
    assert str(fx["leg2"].status) == LegStatus.PLANNED
    # Alert resolved + stamped with approver
    await db_session.refresh(fx["alert"])
    assert str(fx["alert"].status) == AlertStatus.RESOLVED
    assert fx["alert"].acknowledged_by == fx["user"].id
    # Audit entry uses the accept action
    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "accept_delay")))
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].entity_type == "decision"


async def test_execute_reroute_rewrites_legs_at_new_version(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _world(db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user)
    decision = await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="VIA_PIRAEUS", user=fx["user"], now=NOW
    )
    await db_session.commit()

    assert str(decision.action) == "REROUTE"
    assert decision.route_version_before == 1
    assert decision.route_version_after == 2
    assert decision.chosen_option_key == "VIA_PIRAEUS"

    await db_session.refresh(fx["leg2"])
    assert str(fx["leg2"].status) == LegStatus.REPLACED  # planned legs zero-loss replaced

    # New legs at route_version=2, chained to the shipment destination,
    # departure clock starts at `now`, sequenced at 41 km/h over haversine×1.15.
    new_legs = list(
        (
            await db_session.execute(
                select(Leg).where(
                    Leg.shipment_id == fx["shipment"].id,
                    Leg.route_version == 2,
                    Leg.status == LegStatus.PLANNED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(new_legs) == 1
    nl = new_legs[0]
    assert nl.destination_id == fx["shipment"].destination_id
    dep = nl.planned_departure
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=UTC)
    assert abs((dep - NOW).total_seconds()) < 5  # clock chained from approval time
    assert nl.distance_km is not None and nl.distance_km > 0
    expected_hours = nl.distance_km / get_mode_speed("SEA")
    assert (nl.planned_arrival - nl.planned_departure).total_seconds() == pytest.approx(
        expected_hours * 3600, rel=0.01
    )

    # Shipment route_version bumped; decision snapshot contains all 3 options
    await db_session.refresh(fx["shipment"])
    assert fx["shipment"].route_version == 2
    snapshot = json.loads(decision.options_snapshot_json)
    assert len(snapshot) == 3

    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "approve_reroute")))
        .scalars()
        .all()
    )
    assert len(audit) == 1


async def test_execute_duplicate_decision_conflict(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _world(db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user)
    await execute_decision(
        db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=fx["user"], now=NOW
    )
    with pytest.raises(ConflictError):
        await execute_decision(
            db_session, alert_id=fx["alert"].id, option_key="ACCEPT_DELAY", user=fx["user"], now=NOW
        )


async def test_execute_unknown_option_raises_validation_error(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location, seed_admin_user
) -> None:
    fx = await _world(db_session, make_shipment, make_order, make_leg, make_location, seed_admin_user)
    with pytest.raises(ValidationError) as exc_info:
        await execute_decision(
            db_session, alert_id=fx["alert"].id, option_key="BOGUS", user=fx["user"], now=NOW
        )
    assert "BOGUS" in exc_info.value.message


async def test_execute_missing_alert_raises_not_found(
    db_session: AsyncSession, seed_admin_user
) -> None:
    with pytest.raises(ResourceNotFoundError):
        await execute_decision(
            db_session, alert_id="no-alert", option_key="ACCEPT_DELAY", user=seed_admin_user, now=NOW
        )


async def test_execute_generic_divert_succeeds_with_new_template(
    db_session: AsyncSession, make_shipment, make_order, make_leg, seed_admin_user
) -> None:
    """GENERIC placeholder can now be executed via parameter-driven default template."""
    shipment = await make_shipment(status="IN_TRANSIT", container_count=1)
    await make_leg(shipment_id=shipment.id, status=LegStatus.PLANNED)
    await make_order(order_number="ORD-GEN", shipment=shipment)
    disruption = Disruption(
        shipment_id=shipment.id,
        disruption_type="WEATHER",
        status="ACTIVE",
        description="storm",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()
    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity="MEDIUM",
        status="OPEN",
        financial_exposure=0.0,
        sla_breach_details_json="{}",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert, ["disruption"])

    decision = await execute_decision(
        db_session, alert_id=alert.id, option_key="DIVERT_GENERIC", user=seed_admin_user, now=NOW
    )
    assert str(decision.action) == "REROUTE"
    assert decision.chosen_option_key == "DIVERT_GENERIC"
