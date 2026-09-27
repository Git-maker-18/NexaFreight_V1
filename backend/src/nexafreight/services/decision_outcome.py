"""Phase 2 of Task 12: complete DecisionOutcome rows once shipments deliver.

`finalize_decision_outcomes` scans pending outcome rows whose shipment is
DELIVERED and fills the realized picture:

- realized_arrival_delta_h: max actual_arrival over the shipment's DELIVERED
  legs minus max planned_arrival over its REPLACED legs (the plan the
  decision replaced). Positive = later than the replaced plan would have
  arrived.
- realized_penalty_usd: SLA weekly-norm penalty implied by the actual final
  arrival vs each order's sla_deadline. Demurrage is v1 = 0 (needs dwell
  event telemetry that does not exist yet).

Idempotent: finalized rows are skipped, so the drip loop can call this
every tick.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.core import params
from nexafreight.enums import LegStatus, ShipmentStatus
from nexafreight.services.financial_engine import calculate_sla_penalty_weekly
from nexafreight.models import DecisionOutcome, Leg, Order, Shipment


def _aware(dt: datetime) -> datetime:
    """SQLite-friendly tz normalization (E26 pattern)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def finalize_decision_outcomes(session: AsyncSession) -> list[str]:
    """Fill realized_* for delivered shipments; returns finalized outcome ids."""
    now = datetime.now(UTC)
    pending = (
        await session.execute(
            select(DecisionOutcome, Shipment)
            .join(Shipment, Shipment.id == DecisionOutcome.shipment_id)
            .where(
                DecisionOutcome.realized_arrival_delta_h.is_(None),
                Shipment.status == ShipmentStatus.DELIVERED,
            )
        )
    ).all()

    finalized: list[str] = []
    for outcome, shipment in pending:
        leg_rows = (
            await session.execute(select(Leg).where(Leg.shipment_id == shipment.id))
        ).scalars().all()

        actual_arrivals = [
            _aware(l.actual_arrival)
            for l in leg_rows
            if l.status == LegStatus.COMPLETED and l.actual_arrival is not None
        ]
        if not actual_arrivals or outcome.baseline_planned_arrival is None:
            continue  # cannot compute honestly; leave for a later tick

        actual_final = max(actual_arrivals)
        planned_final = _aware(outcome.baseline_planned_arrival)
        delta_h = (actual_final - planned_final).total_seconds() / 3600.0

        orders = (
            await session.execute(select(Order).where(Order.shipment_id == shipment.id))
        ).scalars().all()
        penalty = 0.0
        for order in orders:
            if order.sla_deadline is None:
                continue
            late_h = (actual_final - _aware(order.sla_deadline)).total_seconds() / 3600.0
            if late_h > 0:
                days_late = max(1, math.ceil(late_h / 24.0))
                penalty += calculate_sla_penalty_weekly(
                    order.revenue,
                    params.get_float("sla.penalty_pct_per_week", 0.5) / 100.0,
                    days_late,
                    cap_pct=params.get_float("sla.penalty_cap_pct", 10.0) / 100.0,
                )

        outcome.realized_arrival_delta_h = round(delta_h, 3)
        outcome.realized_penalty_usd = round(penalty, 2)
        outcome.realized_route_version = shipment.route_version
        outcome.outcome_finalized_at = now
        finalized.append(outcome.id)

    await session.flush()
    return finalized
