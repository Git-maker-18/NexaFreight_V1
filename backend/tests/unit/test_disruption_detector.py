"""Unit tests for disruption detection (Definitive Plan — Phase 2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import AlertSeverity, DisruptionType, LegStatus, TransportMode
from nexafreight.models import Leg, Port, PortDailyStat
from nexafreight.services.disruption_detector import (
    MIN_CONGESTION_INDEX,
    check_port_congestion,
    check_vessel_delay,
    classify_severity,
    estimate_delay_hours,
    planned_progress_fraction,
)

# asyncio_mode = "auto" in pyproject.toml — async tests need no marker


def test_estimate_delay_hours_bands_and_multipliers() -> None:
    """Delay estimation derives from empirical dwell parameters and weather multipliers."""
    assert estimate_delay_hours(DisruptionType.VESSEL_DELAY) == 24.0
    assert estimate_delay_hours(DisruptionType.MANUAL) == 24.0
    # Congestion: min(ratio - 1, 3) * p50 + p90_ext; ratio 4.0 -> 3 * 24 + 48 = 120h
    assert estimate_delay_hours(DisruptionType.PORT_CONGESTION, congestion_ratio=4.0) == 120.0
    assert estimate_delay_hours(DisruptionType.PORT_CONGESTION, congestion_ratio=4.0, port_locode="PORT-1") == 120.0
    # Weather with the severe multiplier: 48 × 1.5 = 72
    assert estimate_delay_hours(DisruptionType.WEATHER, weather_severe=True) == 72.0


def test_classify_severity_bands_and_floors() -> None:
    """>72h ⇒ CRITICAL; SLA breach ⇒ at least HIGH."""
    assert classify_severity(6) == AlertSeverity.LOW
    assert classify_severity(30) == AlertSeverity.MEDIUM
    assert classify_severity(60) == AlertSeverity.HIGH
    assert classify_severity(80) == AlertSeverity.CRITICAL
    # Breach floor: a 6h slip with an SLA breach is HIGH
    assert classify_severity(6, has_sla_breach=True) == AlertSeverity.HIGH
    # CRITICAL stays CRITICAL
    assert (
        classify_severity(100, has_sla_breach=True) == AlertSeverity.CRITICAL
    )


async def test_planned_progress_fraction_midpoint() -> None:
    """Progress is half elapsed — and reaches 1.0 past arrival."""
    now = datetime(2026, 1, 1, tzinfo=UTC)

    class _FakeLeg:
        planned_departure = now - timedelta(hours=4)
        planned_arrival = now + timedelta(hours=4)

    assert planned_progress_fraction(_FakeLeg(), now) == 0.5  # type: ignore[arg-type]


async def test_planned_progress_fraction_clamps() -> None:
    """Clamps to [0, 1] before departure and after arrival."""
    now = datetime(2026, 1, 1, tzinfo=UTC)

    class _FakeLeg:
        planned_departure = now
        planned_arrival = now + timedelta(hours=8)

    assert planned_progress_fraction(_FakeLeg(), now - timedelta(hours=1)) == 0.0  # type: ignore[arg-type]
    assert planned_progress_fraction(_FakeLeg(), now + timedelta(hours=9)) == 1.0  # type: ignore[arg-type]


async def test_check_vessel_delay_flags_lagging_leg(
    db_session: AsyncSession, make_leg, make_shipment
) -> None:
    """planned 50% at NOW vs actual 10% — gap 40% > 15% threshold."""
    now = datetime.now(UTC)
    shipment = await make_shipment()
    leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        mode=TransportMode.SEA,
        status=LegStatus.IN_PROGRESS,
        planned_departure=now - timedelta(hours=40),
        planned_arrival=now + timedelta(hours=40),
    )
    candidate = await check_vessel_delay(db_session, leg.id, actual_progress=0.10, now=now)
    assert candidate is not None
    assert candidate.disruption_type == DisruptionType.VESSEL_DELAY
    assert candidate.leg_id == leg.id
    assert candidate.shipment_id == shipment.id
    # gap 0.40 × 80h planned = 32h
    assert candidate.estimated_delay_hours == pytest.approx(32.0, abs=0.6)


async def test_check_vessel_delay_on_track_returns_none(
    db_session: AsyncSession, make_leg, make_shipment
) -> None:
    """Actual progress within the 15% tolerance → no candidate."""
    now = datetime.now(UTC)
    shipment = await make_shipment()
    leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        mode=TransportMode.SEA,
        status=LegStatus.IN_PROGRESS,
        planned_departure=now - timedelta(hours=40),
        planned_arrival=now + timedelta(hours=40),
    )
    assert (
        await check_vessel_delay(db_session, leg.id, actual_progress=0.45, now=now) is None
    )
    # Missing leg → none (no crash)
    assert await check_vessel_delay(db_session, 99999, 0.5, now=now) is None


async def test_check_port_congestion_flags_inbound_shipments(
    db_session: AsyncSession, make_shipment, make_location, make_leg
) -> None:
    """Today 0.8 vs 30-day 0.2 baseline (ratio 4.0) → candidate per inbound shipment."""
    now = datetime.now(UTC)
    loc = await make_location(locode="GRPIR", name="Piraeus")
    port = Port(location_id=loc.id)
    db_session.add(port)
    await db_session.commit()

    for i in range(1, 31):
        db_session.add(
            PortDailyStat(
                port_id=port.id,
                stat_date=(now - timedelta(days=i)).date(),
                congestion_index=0.2,
            )
        )
    db_session.add(
        PortDailyStat(port_id=port.id, stat_date=now.date(), congestion_index=0.8)
    )
    await db_session.commit()

    # Two shipments whose next leg terminates at the congested port
    for i in range(2):
        s = await make_shipment(status="IN_TRANSIT")
        await make_leg(
            shipment_id=s.id,
            sequence_number=1,
            mode=TransportMode.SEA,
            status=LegStatus.PLANNED,
            destination=loc,
        )

    candidates = await check_port_congestion(db_session, now=now)
    assert len(candidates) == 2
    for c in candidates:
        # GRPIR calibrated dwell: min(4.0 - 1, 3) * 20 + 40 = 100h
        assert c.estimated_delay_hours == pytest.approx(100.0)
        assert "Piraeus" in c.description or "GRPIR" in c.description


async def test_check_port_congestion_respects_min_index_floor(
    db_session: AsyncSession, make_shipment, make_location, make_leg
) -> None:
    """A high ratio with a tiny absolute index stays silent (noise floor)."""
    now = datetime.now(UTC)
    loc = await make_location(locode="QqFLO", name="Floodplain")
    port = Port(location_id=loc.id)
    db_session.add(port)
    await db_session.commit()
    for i in range(1, 31):
        db_session.add(
            PortDailyStat(
                port_id=port.id,
                stat_date=(now - timedelta(days=i)).date(),
                congestion_index=0.1,
            )
        )
    # today 0.4 → ratio 4.0 but below MIN_CONGESTION_INDEX 0.5
    db_session.add(
        PortDailyStat(port_id=port.id, stat_date=now.date(), congestion_index=0.4)
    )
    await db_session.commit()

    s = await make_shipment(status="IN_TRANSIT")
    await make_leg(
        shipment_id=s.id,
        sequence_number=1,
        status=LegStatus.PLANNED,
        destination=loc,
    )
    assert MIN_CONGESTION_INDEX == 0.5
    assert await check_port_congestion(db_session, now=now) == []


async def test_check_port_congestion_ignores_stable_ports(
    db_session: AsyncSession, make_location, make_shipment, make_leg
) -> None:
    """No spike (today ≈ baseline) → no candidates."""
    now = datetime.now(UTC)
    loc = await make_location(locode="USOKP", name="Okayport")
    port = Port(location_id=loc.id)
    db_session.add(port)
    await db_session.commit()
    for i in range(0, 30):
        db_session.add(
            PortDailyStat(
                port_id=port.id,
                stat_date=(now - timedelta(days=i)).date(),
                congestion_index=0.5,
            )
        )
    await db_session.commit()
    s = await make_shipment(status="IN_TRANSIT")
    await make_leg(
        shipment_id=s.id, sequence_number=1, status=LegStatus.PLANNED, destination=loc
    )
    assert await check_port_congestion(db_session, now=now) == []
