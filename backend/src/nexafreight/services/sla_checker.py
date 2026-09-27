"""SLA checker (Definitive Plan — Phase 4).

Continuous SLA surveillance:
    compute_sla_risk(deadline, current_eta)
        ON_TIME → (cushion >= 3d) / LOW (>=1d) / MEDIUM (>=12h) / HIGH (<12h)
        BREACH when the ETA is already past the deadline.
    check_all_in_transit(session)
        Rescores every order on IN_TRANSIT / DELAYED shipments from the
        shipment's current ETA (revised-else-planned) and persists
        Order.sla_status. Skips DELIVERED shipments.
    escalate_unacknowledged(alert)
        CRITICAL alerts still OPEN past the ack SLA (60 min) get an
        immutable escalation entry in the audit trail.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexafreight.core import params
from nexafreight.enums import AlertStatus, LegStatus, OrderSlaStatus, ShipmentStatus
from nexafreight.models import Alert, AuditLog, Order, Shipment
from nexafreight.services.alert_engine import latest_planned_arrival

logger = logging.getLogger(__name__)

#: Minutes a CRITICAL alert may stay unacknowledged before escalation.
ACK_SLA_MINUTES: int = 60




class SlaRisk(StrEnum):
    """SLA risk bands (Definitive Plan Phase 4)."""

    ON_TIME = "ON_TIME"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BREACH = "BREACH"


def compute_sla_risk(
    deadline: datetime | None,
    predicted_p85_arrival: datetime | None,
) -> SlaRisk:
    """SLA risk for an order delivered at predicted_p85_arrival vs deadline.

    - ETA unknown → ON_TIME (no basis to warn)
    - slack < 0 → BREACH
    - slack < 12h → HIGH
    - slack < 36h → MEDIUM
    - Else → ON_TIME

    Note: there is deliberately no LOW band; the persisted OrderSlaStatus
    is the 3-state ON_TIME / AT_RISK / LATE (see _risk_to_order_status).
    """
    if deadline is None or predicted_p85_arrival is None:
        return SlaRisk.ON_TIME
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if predicted_p85_arrival.tzinfo is None:
        predicted_p85_arrival = predicted_p85_arrival.replace(tzinfo=UTC)

    slack_hours = (deadline - predicted_p85_arrival).total_seconds() / 3600.0
    if slack_hours < 0:
        return SlaRisk.BREACH
    if slack_hours < 12.0:
        return SlaRisk.HIGH
    if slack_hours < 36.0:
        return SlaRisk.MEDIUM
    return SlaRisk.ON_TIME


def _risk_to_order_status(risk: SlaRisk) -> OrderSlaStatus:
    """Map the 5-band risk onto the persisted 3-state OrderSlaStatus."""
    if risk is SlaRisk.BREACH:
        return OrderSlaStatus.LATE
    if risk is SlaRisk.ON_TIME:
        return OrderSlaStatus.ON_TIME
    return OrderSlaStatus.AT_RISK


_registry = None

def _get_eta_model():
    global _registry
    if _registry is None:
        from nexafreight.ml.registry import ModelRegistry
        _registry = ModelRegistry()
    return _registry.get_eta_model()

def _predicted_p85(shipment: Shipment, order: Order, session: AsyncSession) -> datetime | None:
    """Gets P85 ETA prediction for an order."""
    base_eta = None
    for alert in shipment.alerts:
        if str(alert.status) == AlertStatus.RESOLVED:
            continue
        try:
            if alert.sla_breach_details_json:
                payload = json.loads(alert.sla_breach_details_json)
                if rev := payload.get("revised_eta"):
                    dt = datetime.fromisoformat(rev)
                    if base_eta is None or dt > base_eta:
                        base_eta = dt
        # E20: narrowed from bare Exception -- only parse/shape errors are
        # skippable here; anything else must surface.
        except (ValueError, TypeError, AttributeError, KeyError, OSError):
            logger.debug("Skipping unreadable sla_breach_details on alert %s", getattr(alert, "id", "?"))
            continue
    if base_eta is None:
        base_eta = latest_planned_arrival(shipment)

    try:
        model = _get_eta_model()
        live_legs = [leg for leg in shipment.legs if str(leg.status) != LegStatus.COMPLETED]
        total_km = sum((leg.distance_km or 0.0) for leg in live_legs)
        leg_count = max(1, len(live_legs))

        order_date = order.order_date or datetime.now(UTC)
        if order_date.tzinfo is None:
            order_date = order_date.replace(tzinfo=UTC)
        deadline = order.sla_deadline
        if deadline and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)

        scheduled_days = max(
            1.0,
            ((deadline - order_date).total_seconds() / 86400.0) if deadline else 15.0,
        )

        features = {
            "shipping_mode": str(shipment.primary_transport_mode),
            "cargo_class": str(order.cargo_class),
            "revenue": float(order.revenue),
            "shipping_cost": float(order.shipping_cost),
            "scheduled_shipping_days": scheduled_days,
            "order_country": (shipment.origin.country_code if shipment.origin else "US"),
            "customer_country": (shipment.destination.country_code if shipment.destination else "US"),
            "product_price": float(order.items[0].unit_price if getattr(order, 'items', None) else order.revenue),
            "order_profit": float(order.revenue - order.shipping_cost),
            "sla_month": deadline.month if deadline else order_date.month,
            "sla_weekday": deadline.weekday() if deadline else order_date.weekday(),
            "sla_quarter": (((deadline.month - 1) // 3 + 1) if deadline else ((order_date.month - 1) // 3 + 1)),
            "total_distance_km": total_km,
            "leg_count": leg_count,
        }
        pred = model.predict(features)
        return order_date + timedelta(days=float(pred.p85_eta_days))
    # E20: intentional broad catch -- availability over correctness. The SLA
    # scan must not crash on any model/feature failure; it degrades to the
    # planned-arrival estimate and the failure is logged.
    except Exception as exc:
        logger.warning("Failed to compute p85 for shipment %s (%s: %s)", shipment.id, type(exc).__name__, exc)
        return base_eta


async def check_all_in_transit(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict:
    """Sweep all IN_TRANSIT / DELAYED shipments and rescore their orders.

    Returns a per-status summary dict for worker logging/telemetry.
    """
    now = now or datetime.now(UTC)

    result = await session.execute(
        select(Shipment).where(
            Shipment.status.in_([ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELAYED])
        )
    )
    shipments = result.scalars().all()

    counts: dict[str, int] = {"ON_TIME": 0, "AT_RISK": 0, "LATE": 0}
    escalated = 0
    checked = 0

    for shipment in shipments:
        await session.refresh(shipment, ["legs", "orders", "alerts"])
        late = False
        for order in shipment.orders:
            p85 = _predicted_p85(shipment, order, session)
            risk = compute_sla_risk(order.sla_deadline, p85)
            status = _risk_to_order_status(risk)
            counts[str(status)] += 1
            if status == OrderSlaStatus.LATE:
                late = True
            order.sla_status = status
            checked += 1

        # Rollup: shipment status mirror (no downgrade over PLANNED state)
        if late and str(shipment.status) != ShipmentStatus.DELAYED:
            shipment.status = ShipmentStatus.DELAYED

        # Escalate stale CRITICAL alerts attached to this shipment.
        for alert in shipment.alerts:
            escalated += int(
                await escalate_unacknowledged(session, alert, now=now)
            )

    await session.flush()
    summary = {
        "shipments_checked": len(shipments),
        "orders_checked": checked,
        "orders_on_time": counts["ON_TIME"],
        "orders_at_risk": counts["AT_RISK"],
        "orders_late": counts["LATE"],
        "alerts_escalated": escalated,
    }
    logger.info("SLA sweep complete: %s", summary)
    return summary


async def escalate_unacknowledged(
    session: AsyncSession,
    alert: Alert,
    *,
    now: datetime | None = None,
    ack_sla_minutes: int = ACK_SLA_MINUTES,
) -> bool:
    """Escalate a CRITICAL alert still OPEN past its ack SLA.

    Writes an immutable AuditLog entry (idempotent per alert).
    Returns True when an escalation entry was written.
    """
    now = now or datetime.now(UTC)

    if str(alert.status) != AlertStatus.OPEN:
        return False
    if str(alert.severity) != "CRITICAL":
        return False

    created = alert.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if now - created < timedelta(minutes=ack_sla_minutes):
        return False

    # Idempotent: one escalation entry per alert.
    existing = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "alert_escalated",
                AuditLog.entity_id == alert.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    age_minutes = (now - created).total_seconds() / 60.0
    session.add(
        AuditLog(
            actor_type="system",
            actor_name="sla_monitor",
            action="alert_escalated",
            entity_type="alert",
            entity_id=alert.id,
            details_json=json.dumps(
                {
                    "severity": str(alert.severity),
                    "status": str(alert.status),
                    "age_minutes": round(age_minutes, 1),
                    "ack_sla_minutes": ack_sla_minutes,
                    "financial_exposure": alert.financial_exposure,
                }
            ),
        )
    )
    await session.flush()
    logger.warning(
        "Escalated unacknowledged CRITICAL alert %s (%.0f min old)", alert.id, age_minutes
    )
    return True
