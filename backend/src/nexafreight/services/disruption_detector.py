"""Disruption detection (Definitive Plan — Phase 2).

Two detectors feed the alert pipeline with ``DetectionCandidate`` value
objects:

1. ``check_vessel_delay`` — compares a leg's *planned* progress fraction
   (time elapsed / time planned) against the *actual* reported progress.
   A gap above 15% flags a vessel delay.
2. ``check_port_congestion`` — daily scan: today's congestion index vs the
   90-day rolling average; when the ratio is >= 1.5 AND today's index is
   material (>= 0.5), every inbound shipment (legs into the port with
   status PLANNED/IN_PROGRESS) gets a candidate.

Delay estimation uses fixed severity bands:
    LOW 12h / MEDIUM 24h / HIGH 48h / CRITICAL 96h
with multipliers: congestion × (ratio − 0.5), severe weather × 1.5.
Severity floors: any SLA breach ⇒ at least HIGH; delay > 72h ⇒ CRITICAL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import (
    AlertSeverity,
    DisruptionType,
    LegStatus,
)
from nexafreight.models import Leg, Port, PortDailyStat, Order

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection constants
# ---------------------------------------------------------------------------

from nexafreight.core import params

#: Progress gap (planned − actual) above which a vessel delay is flagged.
VESSEL_PROGRESS_GAP_THRESHOLD: float = 0.15

#: Absolute congestion index floor — tiny indices are too noisy to trust.
MIN_CONGESTION_INDEX: float = 0.5

#: Rolling baseline window (days) for the congestion average.
BASELINE_DAYS: int = 90


#: Multiplier applied to weather-driven estimates.
WEATHER_SEVERE_MULTIPLIER: float = 1.5

#: Fixed shipment weight assumption used across the plan (t/container).
TONNES_PER_CONTAINER: float = 14.0

_SEVERITY_ORDER = [
    AlertSeverity.LOW,
    AlertSeverity.MEDIUM,
    AlertSeverity.HIGH,
    AlertSeverity.CRITICAL,
]


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionCandidate:
    """A detected-but-not-yet-persisted disruption.

    Producing candidates as value objects keeps detection pure and testable;
    persistence (Disruption row + alert pipeline) happens in the caller.
    """

    disruption_type: DisruptionType
    shipment_id: str | None
    leg_id: int | None
    estimated_delay_hours: float
    description: str
    severity_hint: AlertSeverity


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _floor_severity(severity: AlertSeverity, floor: AlertSeverity) -> AlertSeverity:
    """Raise ``severity`` to at least ``floor``."""
    if _SEVERITY_ORDER.index(severity) < _SEVERITY_ORDER.index(floor):
        return floor
    return severity


def classify_severity(
    estimated_delay_hours: float,
    *,
    sla_cushion_hours: float | None = None,
    has_sla_breach: bool = False,
) -> AlertSeverity:
    """Map an estimated delay to an alert severity.
    
    Now relative to the shipment's SLA cushion if known.
    Floors: >72h ⇒ CRITICAL; any known SLA breach ⇒ at least HIGH.
    """
    if estimated_delay_hours > 72:
        return AlertSeverity.CRITICAL
        
    if sla_cushion_hours is not None:
        if estimated_delay_hours >= sla_cushion_hours:
            sev = AlertSeverity.HIGH
        elif estimated_delay_hours >= sla_cushion_hours * 0.5:
            sev = AlertSeverity.MEDIUM
        else:
            sev = AlertSeverity.LOW
    else:
        if estimated_delay_hours > 48:
            sev = AlertSeverity.HIGH
        elif estimated_delay_hours > 24:
            sev = AlertSeverity.MEDIUM
        else:
            sev = AlertSeverity.LOW

    if has_sla_breach:
        sev = _floor_severity(sev, AlertSeverity.HIGH)
    return sev


def estimate_delay_hours(
    disruption_type: DisruptionType | str,
    *,
    congestion_ratio: float | None = None,
    weather_severe: bool = False,
    port_locode: str | None = None,
) -> float:
    """Estimate disruption delay in hours."""
    dtype = DisruptionType(str(disruption_type))

    if dtype is DisruptionType.PORT_CONGESTION:
        if congestion_ratio is not None:
            default_p50 = params.get_float("port.dwell.p50.default")
            default_p90 = params.get_float("port.dwell.p90_ext.default")
            p50 = params.get_float(f"port.dwell.p50.{port_locode}", default_p50) if port_locode else default_p50
            p90_ext = params.get_float(f"port.dwell.p90_ext.{port_locode}", default_p90) if port_locode else default_p90
            delay = min(congestion_ratio - 1.0, 3.0) * p50
            if congestion_ratio > 2.5:
                delay += p90_ext
            return max(0.0, delay)
        base = params.get_float("disruption.delay.default_h")
    elif dtype is DisruptionType.VESSEL_DELAY:
        base = params.get_float("disruption.delay.vessel_h")
    elif dtype is DisruptionType.WEATHER:
        base = params.get_float("disruption.delay.weather_h")
    else:  # MANUAL and anything unmapped
        base = params.get_float("disruption.delay.default_h")

    hours = base * (WEATHER_SEVERE_MULTIPLIER if weather_severe else 1.0)
    return hours


def planned_progress_fraction(leg: Leg, now: datetime | None = None) -> float:
    """Fraction of a leg's planned duration elapsed at ``now`` (0..1).

    Timezone-safe: naive datetimes are treated as UTC.
    """
    now = now or datetime.now(UTC)

    dep = leg.planned_departure
    arr = leg.planned_arrival
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=UTC)
    if arr.tzinfo is None:
        arr = arr.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    total = (arr - dep).total_seconds()
    if total <= 0:
        return 1.0
    elapsed = (now - dep).total_seconds()
    return max(0.0, min(1.0, elapsed / total))


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


async def check_vessel_delay(
    session: AsyncSession,
    leg_id: int,
    actual_progress: float,
    *,
    now: datetime | None = None,
) -> DetectionCandidate | None:
    """Flag a vessel delay when actual progress lags planned by > threshold.

    Estimated delay = progress gap × the leg's planned duration.
    Returns None when the leg is missing, not SEA/ROAD, or on track.
    """
    leg = await session.get(Leg, leg_id)
    if leg is None:
        return None

    planned = planned_progress_fraction(leg, now)
    gap = planned - max(0.0, min(1.0, actual_progress))
    if gap <= VESSEL_PROGRESS_GAP_THRESHOLD:
        return None

    dep = leg.planned_departure
    arr = leg.planned_arrival
    if dep.tzinfo is None:
        dep = dep.replace(tzinfo=UTC)
    if arr.tzinfo is None:
        arr = arr.replace(tzinfo=UTC)
    planned_hours = max(1.0, (arr - dep).total_seconds() / 3600.0)
    delay_hours = gap * planned_hours

    severity = classify_severity(delay_hours)
    return DetectionCandidate(
        disruption_type=DisruptionType.VESSEL_DELAY,
        shipment_id=leg.shipment_id,
        leg_id=leg.id,
        estimated_delay_hours=round(delay_hours, 2),
        description=(
            f"Vessel behind plan on leg #{leg.sequence_number}: "
            f"{actual_progress:.0%} actual vs {planned:.0%} planned "
            f"(gap {gap:.0%} > {VESSEL_PROGRESS_GAP_THRESHOLD:.0%} threshold)"
        ),
        severity_hint=severity,
    )


async def check_port_congestion(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    min_index: float = MIN_CONGESTION_INDEX,
) -> list[DetectionCandidate]:
    """Daily congestion scan across all ports.

    For each port: today's congestion index vs the 90-day average. When
    ratio >= 1.5 AND index >= min_index, every shipment with a PLANNED or
    IN_PROGRESS leg *into* that port gets a candidate.
    """
    now = now or datetime.now(UTC)
    today: date = now.date()
    baseline_start = today - timedelta(days=BASELINE_DAYS)

    # E25: port.locode lazy-loads Port.location — without eager loading this
    # raises MissingGreenlet under asyncio the moment the ports table has rows
    # (which is why an always-empty table hid it until the demo world).
    ports = (
        await session.execute(select(Port).options(selectinload(Port.location)))
    ).scalars().all()
    candidates: list[DetectionCandidate] = []

    for port in ports:
        rows = (
            await session.execute(
                select(PortDailyStat.stat_date, PortDailyStat.congestion_index).where(
                    PortDailyStat.port_id == port.id,
                    PortDailyStat.stat_date >= baseline_start,
                    PortDailyStat.stat_date <= today,
                )
            )
        ).all()
        if not rows:
            continue

        today_rows = [r for r in rows if r.stat_date == today]
        if not today_rows:
            continue
        today_index = float(today_rows[-1].congestion_index)

        baseline_rows = [r for r in rows if r.stat_date < today]
        if not baseline_rows:
            continue
        baseline_avg = sum(float(r.congestion_index) for r in baseline_rows) / len(baseline_rows)
        if baseline_avg <= 0:
            continue

        ratio = today_index / baseline_avg
        # Tier contract (task 10): WARN at 1.5x baseline triggers the scan's
        # attention; CRITICAL (2.5x, legacy ratio_p90 key) remains available
        # for severity escalation downstream.
        congestion_threshold = params.get_float("disruption.congestion.ratio_warn", 1.5)

        if ratio < congestion_threshold or today_index < min_index:
            continue

        # Inbound shipments: legs ending at this port still en route.
        inbound_legs = (
            await session.execute(
                select(Leg).where(
                    Leg.destination_id == port.location_id,
                    Leg.status.in_([LegStatus.PLANNED, LegStatus.IN_PROGRESS]),
                )
            )
        ).scalars().all()
        seen: set[str] = set()
        for leg in inbound_legs:
            if leg.shipment_id in seen:
                continue
            seen.add(leg.shipment_id)
            locode = port.locode or f"PORT-{port.id}"
            delay = estimate_delay_hours(
                DisruptionType.PORT_CONGESTION, congestion_ratio=ratio, port_locode=locode
            )
            
            # SLA cushion computation
            sla_cushion_hours = None
            orders = (await session.execute(
                select(Order).where(Order.shipment_id == leg.shipment_id)
            )).scalars().all()
            
            cushions = []
            for order in orders:
                if order.sla_deadline and leg.planned_arrival:
                    # E26: normalize BOTH sides — SQLite returns naive
                    # datetimes; mixing naive/aware raises TypeError.
                    arr = leg.planned_arrival if leg.planned_arrival.tzinfo else leg.planned_arrival.replace(tzinfo=UTC)
                    deadline = order.sla_deadline if order.sla_deadline.tzinfo else order.sla_deadline.replace(tzinfo=UTC)
                    c_hours = (deadline - arr).total_seconds() / 3600.0
                    cushions.append(c_hours)
            if cushions:
                sla_cushion_hours = min(cushions)
            
            candidates.append(
                DetectionCandidate(
                    disruption_type=DisruptionType.PORT_CONGESTION,
                    shipment_id=leg.shipment_id,
                    leg_id=leg.id,
                    estimated_delay_hours=round(delay, 2),
                    description=(
                        f"Port congestion at {locode}: index {today_index:.2f} today vs "
                        f"{baseline_avg:.2f} 90-day average (ratio {ratio:.1f})"
                    ),
                    severity_hint=classify_severity(delay, sla_cushion_hours=sla_cushion_hours),
                )
            )

    if candidates:
        logger.warning("Congestion scan flagged %d inbound shipments", len(candidates))
    return candidates
