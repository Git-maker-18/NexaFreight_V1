"""Analytics endpoints (Definitive Plan — Phase 9).

Scorecard (cross-window financials), /financial (P&L breakdown alias),
summary (fleet counts), SLA risk board, and ESG rail. All provenance=DERIVED.

Scorecard windows are *cumulative deadline windows* (an order at deadline
+12h appears in day, week AND month — that is how mornings roll up):
    day   = sla_deadline ≤ now + 1 day
    week  = sla_deadline ≤ now + 7 days
    month = sla_deadline ≤ now + 30 days

Per shipment two financial states:
  decided   — a Decision row exists (approved option) → decided_margin
              booked at revenue − shipping − realized costs.
  undecided — still in transit, pending SLA penalty + demurrage exposure
              estimated from the shipment's current ETA.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.core import params
from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.enums import AlertStatus, DisruptionStatus, OrderSlaStatus, Provenance, ShipmentStatus
from nexafreight.models import Alert, Decision, Shipment, User
from nexafreight.schemas.ops import (
    AnalyticsEsgResponse,
    AnalyticsEsgRow,
    AnalyticsFinancialResponse,
    AnalyticsFinancialRow,
    AnalyticsSlaResponse,
    AnalyticsSlaRow,
    AnalyticsSummaryResponse,
    ProvenanceBucket,
    ShipmentSummaryOut,
    WindowSliceOut,
)
from nexafreight.services.alert_engine import latest_planned_arrival
from nexafreight.services.financial_engine import (
    CO2_G_PER_T_KM,
    DEMURRAGE_DAILY_RATE,
    DEMURRAGE_FREE_DAYS,
    calculate_demurrage,
    calculate_freight_cost,
    calculate_sla_penalty_weekly,
)

router = APIRouter()

TONNES_PER_CONTAINER = 14.0

#: Window bounds (days ahead of now) for the scorecard surfacing.
WINDOW_DAYS: dict[str, float] = {"day": 1.0, "week": 7.0, "month": 30.0}


# ---------------------------------------------------------------------------
# Value objects for window math (testable helpers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShipmentFinancialAggregate:
    """One shipment's numbers for scorecard aggregation."""

    shipment_id: str
    mode: str
    status: str
    revenue_usd: float
    shipping_cost_usd: float
    decided: bool
    realized_cost_usd: float  # penalties + demurrage + freight + carbon realized/decided
    pending_sla_est_usd: float  # projected SLA penalty exposure (undecided only)
    pending_demurrage_est_usd: float  # projected demurrage exposure
    deadlines: list[datetime]  # order deadlines (window membership)
    provenance: str = "DERIVED"  # E12: bake-era (DERIVED/HISTORICAL) vs runtime (SIMULATED)


def window_stats(
    aggregates: list[ShipmentFinancialAggregate],
    *,
    now: datetime,
    window_days: float,
) -> WindowSliceOut:
    """Roll aggregates whose earliest deadline falls inside the window.

    Membership is cumulative: a 12h-deadline order belongs to day AND week
    AND month — the morning scorecard rolls up naturally.
    """
    in_window = [
        a
        for a in aggregates
        if any(
            ((dl if dl.tzinfo is not None else dl.replace(tzinfo=UTC)) - now).total_seconds()
            <= window_days * 86400.0
            for dl in a.deadlines
        )
    ]
    slice_ = WindowSliceOut(period=window_days == 1.0 and "day" or (window_days == 7.0 and "week" or "month"))
    slice_.shipments = len(in_window)
    for a in in_window:
        slice_.total_revenue += a.revenue_usd
        slice_.total_shipping_cost += a.shipping_cost_usd
        if a.decided:
            slice_.decided_margin += a.revenue_usd - a.shipping_cost_usd - a.realized_cost_usd
        else:
            slice_.undecided_revenue += a.revenue_usd
            slice_.undecided_pending_sla_est += a.pending_sla_est_usd
            slice_.undecided_pending_demurrage_est += a.pending_demurrage_est_usd

    # Light rounding for display stability
    for fld in (
        "total_revenue",
        "total_shipping_cost",
        "decided_margin",
        "undecided_revenue",
        "undecided_pending_sla_est",
        "undecided_pending_demurrage_est",
        "undecided_total_pending_est",
    ):
        setattr(slice_, fld, round(getattr(slice_, fld), 2))
    slice_.undecided_total_pending_est = round(
        slice_.undecided_pending_sla_est + slice_.undecided_pending_demurrage_est, 2
    )
    return slice_


def _shipment_freight_carbon(shipment) -> tuple[float, float]:
    """(freight_usd, carbon_usd) nominal across planned + in-progress legs."""
    freight = 0.0
    carbon = 0.0
    weight_t = max(1, shipment.container_count) * TONNES_PER_CONTAINER
    from nexafreight.enums import LegStatus

    for leg in shipment.legs:
        if str(leg.status) == LegStatus.REPLACED:
            continue
        km = leg.distance_km or 0.0
        mode = str(leg.transport_mode)
        freight += calculate_freight_cost(km, weight_t, mode)
        if leg.co2_kg is not None:
            carbon += leg.co2_kg * 0.08
        else:
            factor = CO2_G_PER_T_KM.get(mode, CO2_G_PER_T_KM["SEA"])
            carbon += factor * km * weight_t / 1000.0 * 0.08
    return freight, carbon


def _pending_exposure(
    shipment, *, now: datetime
) -> tuple[float, float, float]:
    """(sla_penalty_est, demurrage_est, realized cost) vs current ETA."""
    eta = latest_planned_arrival(shipment)
    sla_total = 0.0
    demurrage = 0.0
    realized = 0.0
    if eta is not None:
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=UTC)
        for order in shipment.orders:
            deadline = order.sla_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if eta > deadline:
                days_late = max(1, math.ceil((eta - deadline).total_seconds() / 86400.0))
                sla_total += calculate_sla_penalty_weekly(
                    revenue=order.revenue,
                    pct_per_week=params.get_float("sla.penalty_pct_per_week", 0.5) / 100.0,
                    cap_pct=params.get_float("sla.penalty_cap_pct", 10.0) / 100.0,
                    days_late=days_late,
                )
        # Demurrage: dwell already past planned arrival
        dwell_days = max(0, (now - eta).days)
        free_days = int(params.get_int("demurrage.free_days", DEMURRAGE_FREE_DAYS))
        demurrage = calculate_demurrage(
            extra_days=dwell_days,
            free_days=free_days,
            daily_rate=params.get_float("demurrage.rate_inr_per_box_day", 5500.0)
            / params.get_float("fx.usd_inr", 88.0),
        ) * max(1, shipment.container_count)
    # Realized: penalties + demurrage already accounted
    realized = sla_total + demurrage
    return sla_total, demurrage, realized


def _active_world_filter():
    """Era/world guard (audit E3): analytics windows describe the ACTIVE
    demo world only. Shipments whose provenance is in the exclusion list
    (default: HISTORICAL — the 2015–2018 parcel-era ingest) never enter
    day/week/month deadline windows, which are cumulative by design and
    would otherwise pin every historical row inside 'day' forever.
    """
    excluded_raw = str(params.get_str("analytics.exclude_provenances", "HISTORICAL"))
    excluded = {p.strip().upper() for p in excluded_raw.split(",") if p.strip()}
    visible = [p for p in Provenance if p.value not in excluded]
    return Shipment.provenance.in_(visible)


async def _build_aggregates(
    session: AsyncSession, *, now: datetime
) -> list[ShipmentFinancialAggregate]:
    """Fetch shipments and roll up aggregates for window math."""
    result = await session.execute(select(Shipment).where(_active_world_filter()))
    shipments = list(result.scalars().all())

    decided_ids: set[str] = set()
    dres = await session.execute(select(Decision))
    for d in dres.scalars().all():
        decided_ids.add(d.shipment_id)

    aggregates: list[ShipmentFinancialAggregate] = []
    for shipment in shipments:
        await session.refresh(shipment, ["legs", "orders"])
        freight, carbon = _shipment_freight_carbon(shipment)
        sla_est, dem_est, realized = _pending_exposure(shipment, now=now)
        realized_total = realized + freight
        revenue = sum(o.revenue for o in shipment.orders)
        shipping = sum(o.shipping_cost for o in shipment.orders)
        decided = shipment.id in decided_ids
        aggregates.append(
            ShipmentFinancialAggregate(
                shipment_id=shipment.id,
                mode=str(shipment.primary_transport_mode),
                status=str(shipment.status),
                revenue_usd=revenue,
                shipping_cost_usd=shipping,
                decided=decided,
                realized_cost_usd=realized_total if decided else 0.0,
                pending_sla_est_usd=(sla_est if not decided else 0.0),
                pending_demurrage_est_usd=(dem_est if not decided else 0.0),
                deadlines=[o.sla_deadline for o in shipment.orders],
                provenance=str(shipment.provenance),
            )
        )
    return aggregates


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _scorecard_payload(session: AsyncSession) -> AnalyticsFinancialResponse:
    """Shared P&L breakdown builder for /scorecard and the /financial alias."""
    now = datetime.now(UTC)
    aggregates = await _build_aggregates(session, now=now)

    rows_out: list[AnalyticsFinancialRow] = []
    for a in aggregates:
        freight = 0.0
        carbon = 0.0
        # Freight+carbon are the realized freight block; keep them surfaced.
        sla = a.pending_sla_est_usd if not a.decided else 0.0
        dem = a.pending_demurrage_est_usd if not a.decided else 0.0
        realized = a.realized_cost_usd if a.decided else 0.0
        total_costs = a.shipping_cost_usd + realized + sla + dem + freight + carbon
        margin = a.revenue_usd - total_costs
        rows_out.append(
            AnalyticsFinancialRow(
                shipment_id=a.shipment_id,
                mode=a.mode,
                status=a.status,
                revenue_usd=round(a.revenue_usd, 2),
                shipping_cost_usd=round(a.shipping_cost_usd, 2),
                sla_penalty_usd=round(sla, 2),
                demurrage_usd=round(dem, 2),
                freight_cost_usd=round(freight + realized, 2),
                carbon_cost_usd=round(carbon, 2),
                total_costs_usd=round(total_costs, 2),
                margin_usd=round(margin, 2),
                margin_pct=(round(margin / a.revenue_usd, 4) if a.revenue_usd > 0 else None),
            )
        )

    day = window_stats(aggregates, now=now, window_days=WINDOW_DAYS["day"])
    week = window_stats(aggregates, now=now, window_days=WINDOW_DAYS["week"])
    month = window_stats(aggregates, now=now, window_days=WINDOW_DAYS["month"])

    # E12: bake-era vs runtime split -- template-planned (DERIVED/HISTORICAL)
    # and runtime-planner (SIMULATED) shipments roll up side by side, never
    # silently blended.
    by_provenance: dict[str, ProvenanceBucket] = {}
    for a in aggregates:
        bucket = by_provenance.setdefault(a.provenance, ProvenanceBucket())
        bucket.shipments += 1
        bucket.revenue_usd += a.revenue_usd
        bucket.realized_cost_usd += a.realized_cost_usd if a.decided else 0.0
        bucket.pending_sla_est_usd += a.pending_sla_est_usd
        bucket.pending_demurrage_est_usd += a.pending_demurrage_est_usd
    for bucket in by_provenance.values():
        bucket.revenue_usd = round(bucket.revenue_usd, 2)
        bucket.realized_cost_usd = round(bucket.realized_cost_usd, 2)
        bucket.pending_sla_est_usd = round(bucket.pending_sla_est_usd, 2)
        bucket.pending_demurrage_est_usd = round(bucket.pending_demurrage_est_usd, 2)

    return AnalyticsFinancialResponse(
        day=day,
        week=week,
        month=month,
        rows=rows_out,
        provenance="DERIVED",
        by_provenance=by_provenance,
    )


@router.get("/scorecard", response_model=AnalyticsFinancialResponse)
async def scorecard(
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_user),
) -> AnalyticsFinancialResponse:
    """Finance scorecard: day/week/month windows with rows per shipment."""
    return await _scorecard_payload(session)


@router.get("/financial", response_model=AnalyticsFinancialResponse)
async def financial(
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_user),
) -> AnalyticsFinancialResponse:
    """P&L breakdown (Definitive Plan §Phase 8 literal route name).

    Same payload as /scorecard — both are the fleet financial rollup.
    """
    return await _scorecard_payload(session)


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def summary(
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_user),
) -> AnalyticsSummaryResponse:
    """Fleet-state summary (shipments by status, late orders, open alerts)."""
    shipments = list(
        (await session.execute(select(Shipment).where(_active_world_filter()))).scalars().all()
    )
    by_status: dict[str, int] = {}
    total_in_transit = 0
    total_delayed = 0
    total_delivered = 0
    shipments_out: list[ShipmentSummaryOut] = []
    for s in shipments:
        st = str(s.status)
        by_status[st] = by_status.get(st, 0) + 1
        if st == ShipmentStatus.IN_TRANSIT:
            total_in_transit += 1
        elif st == ShipmentStatus.DELAYED:
            total_delayed += 1
        elif st == ShipmentStatus.DELIVERED:
            total_delivered += 1
        shipments_out.append(
            ShipmentSummaryOut(
                id=s.id,
                status=st,
                mode=str(s.primary_transport_mode),
                origin=None,
                destination=None,
            )
        )

    # Orders late count
    from nexafreight.models import Order as OrderModel

    late_count = len(
        list(
            (
                await session.execute(
                    select(OrderModel).where(OrderModel.sla_status == OrderSlaStatus.LATE)
                )
            )
            .scalars()
            .all()
        )
    )

    open_alerts = len(
        list(
            (
                await session.execute(
                    select(Alert).where(Alert.status == AlertStatus.OPEN)
                )
            )
            .scalars()
            .all()
        )
    )

    return AnalyticsSummaryResponse(
        total_shipments=len(shipments),
        in_transit=total_in_transit,
        delivered=total_delivered,
        delayed=total_delayed,
        sla_breach_count=late_count,
        open_alerts=open_alerts,
        summary_by_status=by_status,
        shipments=shipments_out,
        provenance="DERIVED",
    )


@router.get("/sla", response_model=AnalyticsSlaResponse)
async def sla_board(
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_user),
) -> AnalyticsSlaResponse:
    """Per-shipment SLA risk rows (in transit, or any non-empty shipment)."""
    now = datetime.now(UTC)
    shipments = list(
        (await session.execute(select(Shipment).where(_active_world_filter()))).scalars().all()
    )
    rows: list[AnalyticsSlaRow] = []
    for s in shipments:
        await session.refresh(s, ["orders", "legs", "disruptions"])
        if not s.orders:
            continue
        eta = latest_planned_arrival(s)
        worst_order = min(s.orders, key=lambda o: o.sla_deadline)
        deadline = worst_order.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        days_to_deadline = None
        delay_days = 0.0
        if eta is not None:
            if eta.tzinfo is None:
                eta = eta.replace(tzinfo=UTC)
            days_to_deadline = round((deadline - max(eta, now)).total_seconds() / 86400.0, 2)
            if eta > deadline:
                delay_days = round((eta - deadline).total_seconds() / 86400.0, 2)
        disrupted = any(
            str(d.status) == DisruptionStatus.ACTIVE for d in s.disruptions
        )
        desc = next(
            (d.description for d in s.disruptions if str(d.status) == DisruptionStatus.ACTIVE),
            None,
        )
        rows.append(
            AnalyticsSlaRow(
                shipment_id=s.id,
                sla_status=str(worst_order.sla_status),
                days_to_deadline=days_to_deadline,
                disrupted=disrupted,
                disruption_description=desc,
                delay_days=delay_days,
            )
        )
    return AnalyticsSlaResponse(rows=rows, provenance="DERIVED")


@router.get("/esg", response_model=AnalyticsEsgResponse)
async def esg_rail(
    session: AsyncSession = Depends(get_db_session),
    _user: User = Depends(get_current_user),
) -> AnalyticsEsgResponse:
    """CO2 per shipment + vs-air comparison."""
    shipments = list((await session.execute(select(Shipment))).scalars().all())
    rows: list[AnalyticsEsgRow] = []
    breakdown: dict[str, int] = {}
    for s in shipments:
        await session.refresh(s, ["legs"])
        weight_t = max(1, s.container_count) * TONNES_PER_CONTAINER
        from nexafreight.enums import LegStatus

        live_legs = [l for l in s.legs if str(l.status) != LegStatus.REPLACED]
        km = sum(l.distance_km or 0.0 for l in live_legs)
        mode = str(s.primary_transport_mode)
        breakdown[mode] = breakdown.get(mode, 0) + 1

        co2_kg = None
        if all(l.co2_kg is not None for l in live_legs) and live_legs:
            co2_kg = sum(l.co2_kg or 0.0 for l in live_legs)
        else:
            co2_kg = CO2_G_PER_T_KM.get(mode, CO2_G_PER_T_KM["SEA"]) * km * weight_t / 1000.0

        per_container = co2_kg / max(1, s.container_count)

        air_kg = CO2_G_PER_T_KM["AIR"] * km * weight_t / 1000.0
        vs_air_saving = None
        if air_kg > 0:
            vs_air_saving = (1.0 - co2_kg / air_kg) * 100.0

        mode_freight = calculate_freight_cost(km, weight_t, mode)
        air_freight = calculate_freight_cost(km, weight_t, "AIR")
        vs_air_freight_delta = None
        if air_freight > 0:
            vs_air_freight_delta = (mode_freight - air_freight) / air_freight * 100.0

        rows.append(
            AnalyticsEsgRow(
                shipment_id=s.id,
                mode=mode,
                kg_co2=round(co2_kg, 1),
                kg_co2e_per_container=round(per_container, 1),
                vs_air_co2_saving_pct=(round(vs_air_saving, 1) if vs_air_saving is not None else None),
                vs_air_freight_delta_pct=(
                    round(vs_air_freight_delta, 1) if vs_air_freight_delta is not None else None
                ),
            )
        )
    return AnalyticsEsgResponse(rows=rows, route_breakdown=breakdown, provenance="DERIVED")
