"""Unit tests for the SLA checker (Definitive Plan — Phase 4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import AlertSeverity, AlertStatus, OrderSlaStatus, ShipmentStatus
from nexafreight.models import Alert, AuditLog
from nexafreight.services.sla_checker import (
    ACK_SLA_MINUTES,
    SlaRisk,
    check_all_in_transit,
    compute_sla_risk,
    escalate_unacknowledged,
)


NOW = datetime.now(UTC)


def test_compute_sla_risk_bands() -> None:
    """Deadline bands: ON_TIME ≥3d, LOW ≥1d, MEDIUM ≥12h, HIGH <12h, BREACH past."""
    deadline_close = NOW + timedelta(days=1, hours=6)
    deadline_medium = NOW + timedelta(days=1, hours=18)
    deadline_low = NOW + timedelta(days=2)
    deadline_far = NOW + timedelta(days=5)

    assert compute_sla_risk(deadline_far, NOW + timedelta(days=1)) == SlaRisk.ON_TIME
    assert compute_sla_risk(deadline_low, NOW + timedelta(days=1)) == SlaRisk.MEDIUM
    assert compute_sla_risk(deadline_medium, NOW + timedelta(days=1)) == SlaRisk.MEDIUM
    assert compute_sla_risk(deadline_close, NOW + timedelta(days=1)) == SlaRisk.HIGH
    assert compute_sla_risk(NOW - timedelta(days=1), NOW) == SlaRisk.BREACH
    # Missing inputs are benign
    assert compute_sla_risk(None, NOW) == SlaRisk.ON_TIME
    assert compute_sla_risk(deadline_far, None) == SlaRisk.ON_TIME


async def test_check_all_in_transit_updates_statuses(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """In-transit shipment whose planned ETA exceeds deadline → LATE."""
    late_shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment_id=late_shipment.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=11),
    )
    late_order = await make_order(
        order_number="ORD-SLA-LATE",
        shipment=late_shipment,
        sla_deadline=NOW + timedelta(days=5),
    )

    ok_shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment_id=ok_shipment.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=2),
    )
    ok_order = await make_order(
        order_number="ORD-SLA-OK",
        shipment=ok_shipment,
        sla_deadline=NOW + timedelta(days=6),
    )

    summary = await check_all_in_transit(db_session)
    await db_session.commit()

    assert summary["orders_checked"] == 2
    assert summary["orders_late"] == 1
    assert summary["orders_on_time"] == 1
    await db_session.refresh(late_order)
    await db_session.refresh(ok_order)
    assert str(late_order.sla_status) == OrderSlaStatus.LATE
    assert str(ok_order.sla_status) == OrderSlaStatus.ON_TIME


async def test_check_all_in_transit_skips_delivered(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    delivered = await make_shipment(status=ShipmentStatus.DELIVERED)
    await make_leg(shipment_id=delivered.id)
    await make_order(order_number="ORD-SLA-DEL", shipment=delivered)
    summary = await check_all_in_transit(db_session)
    assert summary["shipments_checked"] == 0


async def test_breach_status_marks_shipment_delayed(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment_id=shipment.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=1),
    )
    await make_order(
        order_number="ORD-SLA-BR",
        shipment=shipment,
        sla_deadline=NOW - timedelta(hours=1),  # already past → BREACH
    )
    summary = await check_all_in_transit(db_session)
    await db_session.commit()
    await db_session.refresh(shipment)
    assert summary["orders_late"] == 1
    assert str(shipment.status) == ShipmentStatus.DELAYED


async def _open_alert(
    db_session, shipment, *, severity="CRITICAL", status="OPEN", age_minutes: int = 0
) -> Alert:
    from nexafreight.models import Disruption

    disruption = Disruption(
        shipment_id=shipment.id,
        disruption_type="PORT_CONGESTION",
        status="ACTIVE",
        description="test setup disruption",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()
    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity=severity,
        status=status,
        financial_exposure=12_000.0,
        sla_breach_details_json=json.dumps({"breaches": [], "revised_eta": None}),
    )
    db_session.add(alert)
    await db_session.flush()
    if age_minutes:
        alert.created_at = NOW - timedelta(minutes=age_minutes)
    return alert


async def test_escalate_unacknowledged_critical_writes_audit(
    db_session: AsyncSession, make_shipment
) -> None:
    """CRITICAL alert OPEN for 90min → audit entry written."""
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    alert = await _open_alert(db_session, shipment, age_minutes=90)

    written = await escalate_unacknowledged(db_session, alert, now=NOW)
    await db_session.commit()
    assert written is True

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "alert_escalated")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity_type == "alert"
    assert rows[0].entity_id == alert.id

    # Idempotent: second escalation for the same alert is a no-op
    assert await escalate_unacknowledged(db_session, alert, now=NOW) is False


async def test_escalate_skips_fresh_and_low_severity(
    db_session: AsyncSession, make_shipment
) -> None:
    """30-minute-old CRITICAL stays quiet; 90-minute HIGH stays quiet."""
    assert ACK_SLA_MINUTES == 60
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)

    fresh_critical = await _open_alert(db_session, shipment, age_minutes=30)
    assert await escalate_unacknowledged(db_session, fresh_critical, now=NOW) is False

    stale_high = await _open_alert(db_session, shipment, severity="HIGH", age_minutes=90)
    assert await escalate_unacknowledged(db_session, stale_high, now=NOW) is False


async def test_escalate_skips_acknowledged(
    db_session: AsyncSession, make_shipment
) -> None:
    """A stale but acknowledged CRITICAL is NOT escalated."""
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    alert = await _open_alert(
        db_session, shipment, status=AlertStatus.ACKNOWLEDGED, age_minutes=90
    )
    assert await escalate_unacknowledged(db_session, alert, now=NOW) is False


async def test_sweep_escalates_stale_alerts(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """End-to-end: sweep escalates stale CRITICAL alerts on in-transit shipments."""
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(shipment_id=shipment.id)
    await make_order(order_number="ORD-SLA-ESC", shipment=shipment)
    await _open_alert(db_session, shipment, age_minutes=120)

    summary = await check_all_in_transit(db_session)
    await db_session.commit()
    assert summary["alerts_escalated"] == 1
