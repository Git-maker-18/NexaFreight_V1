"""Alert engine (Definitive Plan — Phase 3).

When a disruption is detected, the engine computes its financial impact
per order on the affected shipment, then persists an Alert carrying a
breach breakdown the operator UI and reroute engine consume.

Flow:
    process_disruption(disruption)
    ├─ compute_revised_eta(shipment, disruption)      original ETA + delay
    ├─ check_sla_breaches(shipment, revised_eta)      per-order penalty rows
    ├─ determine_severity(exposure, breach_count)     CRITICAL/HIGH/MEDIUM/LOW
    └─ create_alert(...)                              alerts row (idempotent)

Breach payload persisted on Alert.sla_breach_details_json:
    {
      "breaches": [{order_id, order_number, revenue_usd, days_late, penalty_usd}],
      "sla_penalty_total_usd": float,
      "demurrage_total_usd": float,
      "estimated_delay_hours": float,
      "revised_eta": ISO-8601 | null
    }
Rates come from financial_engine: 5%/day SLA (10% cap), 4 free demurrage
days at $150/container-day.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import (
    AlertSeverity,
    AlertStatus,
    DisruptionStatus,
    LegStatus,
    OrderSlaStatus,
    ShipmentStatus,
)
from nexafreight.core import params
from nexafreight.models import Alert, Disruption, Order, Shipment
from nexafreight.services.financial_engine import (
    DEMURRAGE_DAILY_RATE,
    DEMURRAGE_FREE_DAYS,
    calculate_demurrage,
    calculate_sla_penalty_weekly,
)

logger = logging.getLogger(__name__)

_SEV_ORDER = [
    AlertSeverity.LOW,
    AlertSeverity.MEDIUM,
    AlertSeverity.HIGH,
    AlertSeverity.CRITICAL,
]

#: Exposure bands (USD) for severity classification.
SEVERITY_CRITICAL_USD: float = 10_000.0
SEVERITY_HIGH_USD: float = 2_500.0
SEVERITY_MEDIUM_USD: float = 500.0


# ---------------------------------------------------------------------------
# Impact computation
# ---------------------------------------------------------------------------


def latest_planned_arrival(shipment: Shipment) -> datetime | None:
    """Latest planned arrival across live (non-REPLACED) legs; None if unknown."""
    arrivals = [
        leg.planned_arrival
        for leg in shipment.legs
        if str(leg.status) != LegStatus.REPLACED and leg.planned_arrival is not None
    ]
    return max(arrivals) if arrivals else None


def compute_revised_eta(
    shipment: Shipment,
    estimated_delay_hours: float,
) -> datetime | None:
    """Original latest planned ETA + the estimated delay."""
    latest = latest_planned_arrival(shipment)
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return latest + timedelta(hours=estimated_delay_hours)


def determine_severity(financial_exposure: float, breach_count: int) -> AlertSeverity:
    """CRITICAL/HIGH/MEDIUM/LOW from financial exposure.

    Bands: >= $10k CRITICAL, >= $2.5k HIGH, >= $500 MEDIUM, else LOW.
    An SLA breach never reports below MEDIUM — money compounds quietly.
    """
    if financial_exposure >= SEVERITY_CRITICAL_USD:
        return AlertSeverity.CRITICAL
    if financial_exposure >= SEVERITY_HIGH_USD:
        return AlertSeverity.HIGH
    if financial_exposure >= SEVERITY_MEDIUM_USD:
        return AlertSeverity.MEDIUM
    if breach_count > 0:
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


async def check_sla_breaches(
    session: AsyncSession,
    shipment: Shipment,
    revised_eta: datetime | None,
) -> tuple[list[dict], float]:
    """Per-order SLA breach rows for a shipment at ``revised_eta``.

    A breached order contributes (order_number, revenue, days_late, penalty).
    days_late rounds up — 1 hour late is still a day late.
    """
    if revised_eta is None:
        return [], 0.0
    if revised_eta.tzinfo is None:
        revised_eta = revised_eta.replace(tzinfo=UTC)

    orders = (
        (
            await session.execute(
                select(Order).where(Order.shipment_id == shipment.id)
            )
        )
        .scalars()
        .all()
    )

    breaches: list[dict] = []
    penalty_total = 0.0
    late_flagged = False
    for order in orders:
        deadline = order.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if revised_eta <= deadline:
            # ETA still within deadline — mark AT_RISK if tight (< 1 day)
            if (deadline - revised_eta) < timedelta(days=1):
                if str(order.sla_status) != OrderSlaStatus.LATE:
                    order.sla_status = OrderSlaStatus.AT_RISK
            continue

        days_late = max(1, math.ceil((revised_eta - deadline).total_seconds() / 86400.0))
        # LD norms (calibration batch): 0.5% per week, WEEKLY rounding, cap 10%
        penalty = calculate_sla_penalty_weekly(
            revenue=order.revenue,
            pct_per_week=params.get_float("sla.penalty_pct_per_week", 0.5) / 100.0,
            cap_pct=params.get_float("sla.penalty_cap_pct", 10.0) / 100.0,
            days_late=days_late,
        )
        penalty_total += penalty
        late_flagged = True
        order.sla_status = OrderSlaStatus.LATE
        breaches.append(
            {
                "order_id": order.id,
                "order_number": order.order_number,
                "revenue_usd": order.revenue,
                "days_late": days_late,
                "penalty_usd": round(penalty, 2),
            }
        )

    if late_flagged and str(shipment.status) != ShipmentStatus.DELIVERED:
        shipment.status = ShipmentStatus.DELAYED

    return breaches, penalty_total


def estimate_demurrage(shipment: Shipment, estimated_delay_hours: float) -> float:
    """Demurrage exposure at the destination port for this delay.

    Containers sit free for DEMURRAGE_FREE_DAYS, then pay per container.
    """
    delay_days = math.ceil(estimated_delay_hours / 24.0)
    free_days = int(params.get_int("demurrage.free_days", DEMURRAGE_FREE_DAYS))
    # ₹5,500/box/day (JNPT band mid) converted at the market FX param
    daily_rate_usd = params.get_float("demurrage.rate_inr_per_box_day", 5500.0) / params.get_float(
        "fx.usd_inr", 88.0
    )
    per_container = calculate_demurrage(
        extra_days=delay_days,
        free_days=free_days,
        daily_rate=daily_rate_usd,
    )
    return per_container * max(1, shipment.container_count)


# ---------------------------------------------------------------------------
# Alert persistence
# ---------------------------------------------------------------------------


async def create_alert(
    session: AsyncSession,
    *,
    shipment: Shipment,
    disruption: Disruption,
    breaches: list[dict],
    sla_penalty_total: float,
    demurrage_total: float,
    estimated_delay_hours: float,
    revised_eta: datetime | None,
) -> Alert:
    """Persist the alert row with a structured breach payload (idempotent)."""
    exposure = sla_penalty_total + demurrage_total
    severity = determine_severity(exposure, len(breaches))

    payload = {
        "breaches": breaches,
        "sla_penalty_total_usd": round(sla_penalty_total, 2),
        "demurrage_total_usd": round(demurrage_total, 2),
        "estimated_delay_hours": estimated_delay_hours,
        "revised_eta": revised_eta.isoformat() if revised_eta else None,
    }

    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity=severity,
        status=AlertStatus.OPEN,
        financial_exposure=round(exposure, 2),
        sla_breach_details_json=json.dumps(payload),
    )
    session.add(alert)
    await session.flush()
    return alert


async def process_disruption(
    session: AsyncSession,
    disruption: Disruption,
    *,
    estimated_delay_hours: float | None = None,
) -> Alert | None:
    """Assess a disruption's impact and create its alert.

    Idempotent: a disruption already carrying an alert returns the existing
    alert instead of duplicating it. Returns None when the disruption has
    no shipment context.
    """
    # Idempotency guard: one alert per disruption (schema-enforced too).
    result = await session.execute(
        select(Alert).where(Alert.disruption_id == disruption.id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    shipment = await session.get(Shipment, disruption.shipment_id)
    if shipment is None:
        logger.error("Disruption %s references missing shipment", disruption.id)
        return None

    shipment = (
        (
            await session.execute(
                select(Shipment).where(Shipment.id == disruption.shipment_id)
            )
        )
        .scalars()
        .first()
    )
    # Load legs + orders eagerly inside the greenlet (no lazy access outside it).
    await session.refresh(shipment, ["legs", "orders"])

    delay = estimated_delay_hours if estimated_delay_hours is not None else 24.0
    revised_eta = compute_revised_eta(shipment, delay)
    breaches, penalty_total = await check_sla_breaches(session, shipment, revised_eta)
    demurrage_total = estimate_demurrage(shipment, delay)

    alert = await create_alert(
        session,
        shipment=shipment,
        disruption=disruption,
        breaches=breaches,
        sla_penalty_total=penalty_total,
        demurrage_total=demurrage_total,
        estimated_delay_hours=delay,
        revised_eta=revised_eta,
    )
    logger.warning(
        "Alert %s for shipment %s (%s, exposure $%.2f, %d breaches)",
        alert.id,
        shipment.id,
        alert.severity,
        alert.financial_exposure,
        len(breaches),
    )
    return alert


async def resolve_disruption(session: AsyncSession, disruption: Disruption) -> None:
    """Mark a disruption resolved (resolution of its alert happens separately)."""
    disruption.status = DisruptionStatus.RESOLVED
    disruption.resolved_at = datetime.now(UTC)
    await session.flush()
