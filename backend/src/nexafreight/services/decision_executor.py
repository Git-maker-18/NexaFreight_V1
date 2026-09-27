"""Decision executor (Definitive Plan — Phase 6).

Executes an approved reroute decision:
  1. Regenerates the option slate for the alert (single source of truth —
     the dashboard never sends client-computed costs).
  2. Marks the shipment's remaining planned legs REPLACED (zero-loss
     rerouting: legs are never deleted) and creates replacement legs at an
     incremented route_version from the option's route template.
  3. In-flight (IN_PROGRESS) legs are left untouched — you cannot un-sail a
     leg that has already departed; diversion starts from its destination.
  4. Writes an immutable AuditLog entry and the Decision row with the full
     options snapshot presented to the operator.
  5. Resolves the alert (and its disruption).

Guards:
    ValidationError        — unknown option key
    ConflictError          — the alert already has a decision (one-per-alert)
    ResourceNotFoundError  — missing alert / shipment
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import (
    AlertStatus,
    DecisionAction,
    DisruptionStatus,
    LegStatus,
    Provenance,
)
from nexafreight.exceptions import (
    ConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from nexafreight.models import (
    DecisionOutcome,
    Alert,
    AuditLog,
    Decision,
    Disruption,
    Leg,
    Location,
    Shipment,
    User,
)
from nexafreight.services.reroute_engine import RerouteOption, generate_options

from nexafreight.core import params

logger = logging.getLogger(__name__)

SUPPORTED_MODES: set[str] = {"SEA", "AIR", "ROAD", "RAIL"}


def get_mode_speed(mode: str) -> float:
    """Return effective speed for mode via parameters."""
    return params.get_float(f"mode.speed.{mode.lower()}")


def get_mode_circuity(mode: str) -> float:
    """Return circuity multiplier for mode via parameters."""
    return params.get_float(f"mode.circuity.{mode.lower()}")

#: Template sentinel for the shipment's final destination.
DESTINATION_SENTINEL = "DESTINATION"


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float, *, radius_km: float = 6371.0
) -> float:
    """Great-circle distance between two points on Earth."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def routed_distance_km(origin: Location, destination: Location, mode: str) -> float:
    """Great-circle distance × mode circuity factor."""
    gc = haversine_km(
        origin.latitude, origin.longitude, destination.latitude, destination.longitude
    )
    return gc * get_mode_circuity(mode)


# ---------------------------------------------------------------------------
# Leg rewriting
# ---------------------------------------------------------------------------


async def _replace_old_legs(session: AsyncSession, shipment_id: str) -> list[Leg]:
    """Mark every remaining PLANNED leg REPLACED. Returns affected legs."""
    result = await session.execute(
        select(Leg).where(
            Leg.shipment_id == shipment_id, Leg.status == LegStatus.PLANNED
        )
    )
    legs = list(result.scalars().all())
    for leg in legs:
        leg.status = LegStatus.REPLACED
    await session.flush()
    return legs


async def _create_new_legs(
    session: AsyncSession,
    shipment: Shipment,
    option: RerouteOption,
    route_version: int,
    *,
    now: datetime,
) -> list[Leg]:
    """Create replacement legs from the chosen option's route template.

    Template shape: ``{"legs": [{"mode": "SEA", "to": "GRPIR"}, ...]}`` —
    ``to`` is a UN/LOCODE or the DESTINATION sentinel. The chain starts at
    the destination of the last non-replaced leg (IN_PROGRESS legs finish
    where they finish) and ends at the shipment's destination.
    """
    template_legs = (option.route_template or {}).get("legs") or []
    if not template_legs:
        raise ValidationError(
            f"Reroute option '{option.option_key}' has no route template to execute"
        )

    await session.refresh(shipment, ["legs"])
    live_legs = [leg for leg in shipment.legs if str(leg.status) != LegStatus.REPLACED]
    # Highest sequence number in use so new legs append, never collide.
    seq = max((leg.sequence_number for leg in shipment.legs), default=0)

    # Anchor: destination of the last non-replaced leg, else shipment origin.
    if live_legs:
        anchor_id = max(live_legs, key=lambda l: l.sequence_number).destination_id
    else:
        anchor_id = shipment.origin_id
    anchor = await session.get(Location, anchor_id)
    if anchor is None:
        raise ResourceNotFoundError("Location", str(anchor_id))

    destination = await session.get(Location, shipment.destination_id)
    if destination is None:
        raise ResourceNotFoundError("Location", str(shipment.destination_id))

    weight_t = max(1, shipment.container_count) * 14.0
    from nexafreight.services.financial_engine import calculate_co2_kg

    plan_rows: list[tuple[int, str, Location, Location, float, float, float]] = []
    cursor = anchor

    for idx, tpl in enumerate(template_legs):
        is_final = idx == len(template_legs) - 1
        mode = str(tpl["mode"]).upper()
        if mode not in SUPPORTED_MODES:
            raise ValidationError(f"Unsupported transport mode in template: {mode!r}")

        to_locode = tpl.get("to")
        if is_final or to_locode in (None, DESTINATION_SENTINEL):
            to_loc = destination
        else:
            result = await session.execute(
                select(Location).where(Location.locode == str(to_locode))
            )
            to_loc = result.scalar_one_or_none()
            if to_loc is None:
                raise ResourceNotFoundError("Location", str(to_locode))

        distance = routed_distance_km(cursor, to_loc, mode)
        speed = get_mode_speed(mode)
        duration_hours = (distance / speed) if speed > 0 else 0.0
        co2 = calculate_co2_kg(distance, weight_t, mode)

        seq += 1
        plan_rows.append((seq, mode, cursor, to_loc, distance, duration_hours, co2))
        cursor = to_loc

    # Emit the actual ORM rows with a chained departure clock: first
    # replacement leg departs at `now`, each subsequent leg departs when
    # the previous one arrives.
    created: list[Leg] = []
    clock = now
    for seq_no, mode, frm, to_loc, distance, duration_hours, co2 in plan_rows:
        planned_departure = clock
        planned_arrival = clock + timedelta(hours=duration_hours)
        row = Leg(
            shipment_id=shipment.id,
            sequence_number=seq_no,
            route_version=route_version,
            transport_mode=mode,
            status=LegStatus.PLANNED,
            origin_id=frm.id,
            destination_id=to_loc.id,
            planned_departure=planned_departure,
            planned_arrival=planned_arrival,
            distance_km=round(distance, 2),
            co2_kg=round(co2, 3),
        )
        row.provenance = Provenance.DERIVED
        session.add(row)
        created.append(row)
        clock = planned_arrival

    await session.flush()
    return created


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _aware_dt(dt: datetime) -> datetime:
    """SQLite-friendly tz normalization (E26 pattern)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def execute_decision(
    session: AsyncSession,
    *,
    alert_id: str,
    option_key: str,
    user: User,
    now: datetime | None = None,
) -> Decision:
    """Execute an operator's approved option for an alert.

    One decision per alert. Slate is regenerated server-side so the cost
    that lands in the audit trail can never be client-tampered.

    Raises:
        ValidationError: unknown option key, or alert already decided
        ResourceNotFoundError: missing alert or shipment
    """
    now = now or datetime.now(UTC)

    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise ResourceNotFoundError("Alert", alert_id)

    # One decision per alert.
    existing = (
        await session.execute(select(Decision).where(Decision.alert_id == alert_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"Alert {alert_id} already has a decision; cannot approve twice")

    shipment = await session.get(Shipment, alert.shipment_id)
    if shipment is None:
        raise ResourceNotFoundError("Shipment", alert.shipment_id)

    options = await generate_options(session, alert, now=now)
    chosen = next((o for o in options if o.option_key == option_key), None)
    if chosen is None:
        raise ValidationError(
            f"Unknown option_key {option_key!r}. Valid: {[o.option_key for o in options]}"
        )

    # Defer the freshest option objects for the audit snapshot.
    options_snapshot = [o.to_dict() for o in options]

    route_before = shipment.route_version
    route_after = route_before
    # Baseline for the outcome row: final planned arrival of the plan as it
    # stands at decision time (replaced legs keep planned_arrival, so this is
    # stable for REROUTE too).
    pre_legs = (
        await session.execute(select(Leg).where(Leg.shipment_id == shipment.id))
    ).scalars().all()
    pre_planned = [
        _aware_dt(l.planned_arrival) for l in pre_legs if l.planned_arrival is not None
    ]
    baseline_arrival = max(pre_planned) if pre_planned else None
    if chosen.action is DecisionAction.REROUTE:
        route_after = route_before + 1
        replaced = await _replace_old_legs(session, shipment.id)
        shipment.route_version = route_after
        await _create_new_legs(session, shipment, chosen, route_after, now=now)
        logger.info(
            "Decision: rerouted shipment %s — %d legs replaced, v%d → v%d",
            shipment.id,
            len(replaced),
            route_before,
            route_after,
        )

    # Resolve alert + disruption
    alert.status = AlertStatus.RESOLVED
    alert.acknowledged_by = user.id
    alert.acknowledged_at = now
    disruption = await session.get(Disruption, alert.disruption_id)
    if disruption is not None:
        disruption.status = DisruptionStatus.RESOLVED
        disruption.resolved_at = now

    decision = Decision(
        alert_id=alert.id,
        shipment_id=shipment.id,
        action=chosen.action,
        chosen_option_key=chosen.option_key,
        options_snapshot_json=json.dumps(options_snapshot),
        financial_impact=round(chosen.total_impact_usd, 2),
        route_version_before=route_before,
        route_version_after=route_after,
        approved_by=user.id,
    )
    session.add(decision)
    await session.flush()

    action = "accept_delay" if chosen.action is DecisionAction.ACCEPT_DELAY else "approve_reroute"
    session.add(
        AuditLog(
            actor_type="user",
            actor_id=user.id,
            actor_name=(getattr(user, "full_name", None) or getattr(user, "email", "operator")),
            action=action,
            entity_type="decision",
            entity_id=decision.id,
            details_json=json.dumps(
                {
                    "alert_id": alert_id,
                    "shipment_id": shipment.id,
                    "option_key": chosen.option_key,
                    "financial_impact": chosen.total_impact_usd,
                    "route_version_before": route_before,
                    "route_version_after": route_after,
                }
            ),
        )
    )
    # Task 12: freeze the predicted picture + recommendation into a
    # learnable outcome row (phase 1; phase 2 runs at shipment delivery).
    recommended = next((o for o in options if o.recommended), None)
    override = None
    if recommended is not None and recommended.option_key != chosen.option_key:
        override = (
            f"operator chose {chosen.option_key} over recommended "
            f"{recommended.option_key}"
        )
    session.add(
        DecisionOutcome(
            decision_id=decision.id,
            shipment_id=shipment.id,
            chosen_option_key=chosen.option_key,
            recommended_option_key=recommended.option_key if recommended else None,
            override_reason=override,
            predicted_total_impact_usd=round(chosen.total_impact_usd, 2),
            predicted_cost_delta_usd=round(chosen.cost_delta_usd, 2),
            predicted_sla_usd=round(chosen.sla_penalty_usd, 2),
            predicted_demurrage_usd=round(chosen.demurrage_usd, 2),
            predicted_carbon_usd=round(chosen.carbon_cost_usd, 2),
            predicted_revised_eta=chosen.revised_eta,
            baseline_planned_arrival=baseline_arrival,
        )
    )
    await session.flush()
    return decision
