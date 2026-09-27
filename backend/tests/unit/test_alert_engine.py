"""Unit tests for the alert engine (Definitive Plan — Phase 3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import (
    AlertSeverity,
    AlertStatus,
    DisruptionStatus,
    DisruptionType,
    OrderSlaStatus,
    ShipmentStatus,
)
from nexafreight.models import Alert, Disruption
from nexafreight.services.alert_engine import (
    check_sla_breaches,
    compute_revised_eta,
    determine_severity,
    estimate_demurrage,
    process_disruption,
    resolve_disruption,
)


NOW = datetime.now(UTC)


async def _shipment_with_orders(
    db_session, make_shipment, make_order, make_leg, sla_delta_hours: float
):
    """Shipment, one live leg (+4h) and one order whose deadline is controllable."""
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        planned_departure=NOW - timedelta(hours=1),
        planned_arrival=NOW + timedelta(hours=4),
    )
    order = await make_order(
        order_number=f"ORD-AE-{sla_delta_hours}",
        shipment=shipment,
        revenue=50_000.0,
        shipping_cost=3_000.0,
        sla_deadline=NOW + timedelta(hours=sla_delta_hours),
    )
    return shipment, order


async def _disruption(db_session, shipment_id: str) -> Disruption:
    disruption = Disruption(
        shipment_id=shipment_id,
        disruption_type=DisruptionType.PORT_CONGESTION,
        status=DisruptionStatus.ACTIVE,
        description="congestion",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()
    return disruption


async def test_process_disruption_breach_alert_payload(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """36h delay with deadline +20h → breach, alert carries the payload."""
    shipment, order = await _shipment_with_orders(
        db_session, make_shipment, make_order, make_leg, sla_delta_hours=20
    )
    disruption = await _disruption(db_session, shipment.id)

    alert = await process_disruption(db_session, disruption, estimated_delay_hours=36.0)
    await db_session.commit()

    assert alert is not None
    payload = json.loads(alert.sla_breach_details_json)
    assert payload["estimated_delay_hours"] == 36.0
    assert len(payload["breaches"]) == 1
    breach = payload["breaches"][0]
    assert breach["order_number"] == order.order_number
    assert breach["days_late"] == 1
    # LD norms: 1 day late = 1 part-week → 50000 × 0.5% × 1 = 250 (was 2500)
    assert breach["penalty_usd"] == 250.0
    assert alert.financial_exposure == 250.0
    # breaching floor keeps it MEDIUM (exposure 250 < $500 MEDIUM band)
    assert str(alert.severity) == "MEDIUM"


async def test_process_disruption_is_idempotent(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """Second call for the same disruption returns the same alert row."""
    shipment, _ = await _shipment_with_orders(
        db_session, make_shipment, make_order, make_leg, sla_delta_hours=72
    )
    disruption = await _disruption(db_session, shipment.id)
    first = await process_disruption(db_session, disruption, estimated_delay_hours=12.0)
    second = await process_disruption(db_session, disruption, estimated_delay_hours=12.0)
    assert first is not None and second is not None
    assert first.id == second.id


async def test_process_disruption_no_orders_zero_exposure(
    db_session: AsyncSession, make_shipment, make_leg
) -> None:
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(shipment_id=shipment.id, sequence_number=1)
    disruption = await _disruption(db_session, shipment.id)

    alert = await process_disruption(db_session, disruption, estimated_delay_hours=24.0)
    assert alert is not None
    # Demurrage: 1 day delay < 4 free days → 0; no orders → no penalties
    assert alert.financial_exposure == 0.0
    assert str(alert.severity) == "LOW"


def test_determine_severity_bands() -> None:
    assert determine_severity(15_000.0, 0) == AlertSeverity.CRITICAL
    assert determine_severity(10_000.0, 1) == AlertSeverity.CRITICAL
    assert determine_severity(5_000.0, 0) == AlertSeverity.HIGH
    assert determine_severity(600.0, 0) == AlertSeverity.MEDIUM
    assert determine_severity(100.0, 1) == AlertSeverity.MEDIUM  # breach floor
    assert determine_severity(100.0, 0) == AlertSeverity.LOW


async def test_check_sla_breaches_flags_order_late(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    shipment, order = await _shipment_with_orders(
        db_session, make_shipment, make_order, make_leg, sla_delta_hours=8
    )
    # Revised ETA 24h past deadline → 1 day late
    revised = order.sla_deadline + timedelta(hours=24)
    breaches, penalty = await check_sla_breaches(db_session, shipment, revised)
    await db_session.commit()
    assert len(breaches) == 1
    assert penalty == 250.0  # 50000 × 0.5% × 1 part-week (LD norms)
    assert str(order.sla_status) == OrderSlaStatus.LATE
    assert str(shipment.status) == ShipmentStatus.DELAYED


async def test_check_sla_breaches_marks_tight_eta_at_risk(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """ETA within 24h of the deadline without breach → AT_RISK."""
    shipment, order = await _shipment_with_orders(
        db_session, make_shipment, make_order, make_leg, sla_delta_hours=30
    )
    revised = NOW + timedelta(days=1)  # 6h before deadline — tight but OK
    breaches, penalty = await check_sla_breaches(db_session, shipment, revised)
    assert breaches == []
    assert penalty == 0.0
    assert str(order.sla_status) == OrderSlaStatus.AT_RISK


async def test_resolve_disruption_marks_resolved(
    db_session: AsyncSession, make_shipment
) -> None:
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    disruption = await _disruption(db_session, shipment.id)
    await resolve_disruption(db_session, disruption)
    await db_session.commit()
    assert str(disruption.status) == DisruptionStatus.RESOLVED
    assert disruption.resolved_at is not None


def test_estimate_demurrage_scaling() -> None:
    """Demurrage: 4 free days; delay < 4 days free; 5-day delay × containers."""
    assert estimate_demurrage.__name__ == "estimate_demurrage"

    class _Sh:
        container_count = 2

    assert estimate_demurrage(_Sh(), 24.0) == 0.0  # 1 day < 4 free
    # 5 days -> 1 billable day x (Rs5,500 / fx 95.8) x 2 containers
    assert estimate_demurrage(_Sh(), 24.0 * 5) == pytest.approx(5500.0 / 95.8 * 2)
