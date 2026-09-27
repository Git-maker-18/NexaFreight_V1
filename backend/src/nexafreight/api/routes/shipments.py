"""Shipment management endpoints."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.enums import ShipmentStatus, TransportMode
from nexafreight.models import Alert, AuditLog, Leg, Order, Shipment, User
from nexafreight.schemas.common import PaginatedResponse
from nexafreight.schemas.shipment import (
    LegDetail,
    OrderSummary,
    RouteFeature,
    RouteFeatureCollection,
    ShipmentDetail,
    ShipmentEvent,
    ShipmentListItem,
    VesselInfo,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# T-021: List Endpoint
# ============================================================================


@router.get("", response_model=PaginatedResponse[ShipmentListItem])
@router.get("/", response_model=PaginatedResponse[ShipmentListItem])
async def list_shipments(
    status: ShipmentStatus | None = Query(None, description="Filter by status"),
    mode: TransportMode | None = Query(None, alias="mode", description="Filter by transport mode"),
    alert: bool | None = Query(None, description="Only shipments with active alerts"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[ShipmentListItem]:
    """List shipments with optional filters and pagination.

    Returns a paginated list of shipments visible to the authenticated user.
    Supports filtering by status, transport mode, and presence of active alerts.

    Query Parameters:
        status: Filter to shipments with this exact status
        mode: Filter to shipments using this primary transport mode
        alert: If true, only shipments with at least one active alert
        page: Page number (1-indexed, default 1)
        size: Items per page (default 20, max 100)

    Returns:
        Paginated response with shipment list items and metadata

    Authentication:
        Requires any authenticated user (no specific role restriction for read-only list)

    Performance:
        - Uses composite index (status, primary_transport_mode) when both filters present
        - Eager-loads origin/destination locations to avoid N+1 queries
        - Alert filter uses EXISTS subquery to avoid row duplication
    """

    # Build base query with eager loading for locations (avoid N+1)
    query = select(Shipment).options(
        joinedload(Shipment.origin),
        joinedload(Shipment.destination),
    )

    # Apply filters (AND logic)
    filters = []
    if status is not None:
        filters.append(Shipment.status == status)
    if mode is not None:
        filters.append(Shipment.primary_transport_mode == mode)
    if alert is True:
        # EXISTS subquery: only shipments with at least one active alert
        # Avoids row duplication if shipment has multiple alerts
        alert_exists = exists(
            select(1)
            .select_from(Alert)
            .where(
                and_(
                    Alert.shipment_id == Shipment.id,
                    Alert.status.in_(["OPEN", "ACKNOWLEDGED"]),  # Active alert statuses
                )
            )
        )
        filters.append(alert_exists)

    if filters:
        query = query.where(and_(*filters))

    # Default ordering: most urgent SLA first (nulls last), then by created_at desc
    query = query.order_by(
        Shipment.strictest_sla_deadline.asc().nullslast(),
        Shipment.created_at.desc(),
    )

    # Get total count (before pagination)
    count_query = select(func.count()).select_from(Shipment)
    if filters:
        count_query = count_query.where(and_(*filters))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * size
    query = query.limit(size).offset(offset)

    # Execute paginated query
    result = await db.execute(query)
    shipments = result.scalars().unique().all()

    # Convert to response items
    items = []
    for shipment in shipments:
        # Get latest leg for naive ETA placeholder
        # PLACEHOLDER LOGIC: Uses planned_arrival from latest leg by sequence_number.
        # ML-based ETA prediction (T-040/T-043) will replace this later.
        leg_result = await db.execute(
            select(Leg.planned_arrival)
            .where(Leg.shipment_id == shipment.id)
            .order_by(Leg.sequence_number.desc())
            .limit(1)
        )
        latest_leg_eta = leg_result.scalar_one_or_none()

        items.append(
            ShipmentListItem(
                id=shipment.id,
                origin=shipment.origin.locode,  # Eager-loaded, no N+1
                destination=shipment.destination.locode,  # Eager-loaded, no N+1
                mode=shipment.primary_transport_mode,
                status=shipment.status,
                strictest_sla_deadline=shipment.strictest_sla_deadline,
                revised_eta=latest_leg_eta,  # Placeholder until T-040/T-043
            )
        )

    # Calculate total pages
    total_pages = (total + size - 1) // size if total > 0 else 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
    )


# ============================================================================
# T-022: Detail Endpoints
# ============================================================================


def derive_route_quality(provenance: str) -> str:
    """Derive route quality classification from provenance.

    DESIGN DECISION: route_quality is a new derived field introduced in T-022.
    It does not exist in the T-007 database schema. Derivation logic:

    - "high": REAL or CALIBRATED (actual tracking data)
    - "medium": REPLAYED or DERIVED (historical/computed data)
    - "low": SIMULATED or MOCK (synthetic test data)

    Args:
        provenance: Provenance enum value as string

    Returns:
        Quality level: "high", "medium", or "low"
    """
    if provenance in ("REAL", "CALIBRATED"):
        return "high"
    elif provenance in ("REPLAYED", "DERIVED"):
        return "medium"
    else:  # SIMULATED, MOCK
        return "low"


@router.get("/{shipment_id}", response_model=ShipmentDetail)
async def get_shipment_detail(
    shipment_id: str = Path(..., description="Shipment UUID"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ShipmentDetail:
    """Get full shipment detail including legs and orders.

    Loads complete shipment information with:
    - All route segments (legs) in sequence order
    - All associated orders with SLA status
    - Origin/destination location details

    Args:
        shipment_id: Shipment UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        Full shipment detail with nested legs and orders

    Raises:
        HTTPException: 404 if shipment not found

    Performance:
        - Eager-loads legs, orders, and locations in single query (no N+1)
        - Legs ordered by sequence_number
    """
    # Load shipment with eager-loaded relationships
    query = (
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            joinedload(Shipment.origin),
            joinedload(Shipment.destination),
            joinedload(Shipment.legs).joinedload(Leg.origin),
            joinedload(Shipment.legs).joinedload(Leg.destination),
            joinedload(Shipment.legs).joinedload(Leg.vessel),
            joinedload(Shipment.orders),
            joinedload(Shipment.orders).joinedload(Order.shipper),
            joinedload(Shipment.orders).joinedload(Order.consignee),
            joinedload(Shipment.orders).joinedload(Order.carrier),
        )
    )

    result = await db.execute(query)
    shipment = result.unique().scalar_one_or_none()

    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

    # Convert legs to LegDetail schema (ordered by sequence)
    leg_details = []
    for leg in sorted(shipment.legs, key=lambda leg_item: leg_item.sequence_number):
        vessel_info = None
        if leg.vessel:
            vessel_info = VesselInfo(
                name=leg.vessel.name,
                mmsi=leg.vessel.mmsi,
            )

        leg_details.append(
            LegDetail(
                id=leg.id,
                sequence_number=leg.sequence_number,
                mode=leg.transport_mode,
                status=leg.status,
                route_version=leg.route_version,
                origin=leg.origin.locode,
                destination=leg.destination.locode,
                vessel=vessel_info,
                flight_number=leg.flight_number,
                planned_departure=leg.planned_departure,
                planned_arrival=leg.planned_arrival,
                actual_departure=leg.actual_departure,
                actual_arrival=leg.actual_arrival,
                distance_km=leg.distance_km,
                co2_kg=leg.co2_kg,
                provenance=leg.provenance,
            )
        )

    # Convert orders to OrderSummary schema
    order_summaries = [
        OrderSummary(
            id=order.id,
            order_number=order.order_number,
            sla_deadline=order.sla_deadline,
            revenue=order.revenue,
            sla_status=order.sla_status,
            shipper=order.shipper.name if order.shipper else None,
            consignee=order.consignee.name if order.consignee else None,
            carrier=order.carrier.name if order.carrier else None,
        )
        for order in shipment.orders
    ]

    return ShipmentDetail(
        id=shipment.id,
        origin=shipment.origin.locode,
        destination=shipment.destination.locode,
        mode=shipment.primary_transport_mode,
        cargo_class=shipment.cargo_class,
        status=shipment.status,
        route_version=shipment.route_version,
        strictest_sla_deadline=shipment.strictest_sla_deadline,
        container_count=shipment.container_count,
        legs=leg_details,
        orders=order_summaries,
    )


@router.get("/{shipment_id}/route", response_model=RouteFeatureCollection)
async def get_shipment_route(
    shipment_id: str = Path(..., description="Shipment UUID"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> RouteFeatureCollection:
    """Get shipment route as GeoJSON FeatureCollection.

    Returns route geometry for map visualization. Each leg becomes one
    GeoJSON Feature with mode, provenance, and derived route_quality.

    Args:
        shipment_id: Shipment UUID
        db: Database session
        current_user: Authenticated user

    Returns:
        GeoJSON FeatureCollection with one Feature per leg

    Raises:
        HTTPException: 404 if shipment not found

    Behavior:
        - Returns empty FeatureCollection (not error) if shipment has no legs
        - Skips legs with malformed/missing geometry (logs warning, continues)
        - Features ordered by leg sequence_number

    DESIGN DECISION: Malformed geometry handling
    If a leg's stored route_geometry_json is invalid/missing, that leg is
    SKIPPED with a logged warning, and remaining valid legs are still returned.
    This "graceful degradation" approach is more useful for dashboards than
    failing the entire route view due to one corrupted leg.
    """
    # Verify shipment exists
    shipment_exists = await db.execute(select(exists().where(Shipment.id == shipment_id)))
    if not shipment_exists.scalar():
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

    # Load legs with geometry
    legs_result = await db.execute(
        select(Leg).where(Leg.shipment_id == shipment_id).order_by(Leg.sequence_number)
    )
    legs = legs_result.scalars().all()

    # Build GeoJSON features
    features = []
    for leg in legs:
        # Parse stored geometry JSON
        if not leg.route_geometry_json:
            logger.warning(f"Leg {leg.id} (shipment {shipment_id}) has no route geometry, skipping")
            continue

        try:
            geometry = json.loads(leg.route_geometry_json)
        except json.JSONDecodeError as e:
            logger.warning(
                f"Leg {leg.id} (shipment {shipment_id}) has malformed geometry JSON: {e}, skipping"
            )
            continue

        # Derive route quality from provenance
        provenance_str = str(leg.provenance)
        quality = derive_route_quality(provenance_str)

        features.append(
            RouteFeature(
                type="Feature",
                geometry=geometry,
                properties={
                    "leg_id": leg.id,
                    "sequence": leg.sequence_number,
                    "mode": leg.transport_mode,
                    "provenance": leg.provenance,
                    "route_quality": quality,
                    "status": leg.status,
                },
            )
        )

    return RouteFeatureCollection(
        type="FeatureCollection",
        features=features,
    )


@router.get("/{shipment_id}/events", response_model=PaginatedResponse[ShipmentEvent])
async def get_shipment_events(
    shipment_id: str = Path(..., description="Shipment UUID"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[ShipmentEvent]:
    """Get shipment event history from audit log.

    Returns paginated events sourced from AuditLog table (no dedicated
    ShipmentEvent table exists in T-007 schema).

    NOTE: This endpoint will return sparse/empty results until later tasks
    (T-044+ disruptions, alerts, decisions) begin writing real audit entries.
    An empty event list is correct and expected at this stage of the project.

    Args:
        shipment_id: Shipment UUID
        page: Page number (1-indexed)
        size: Items per page (max 100)
        db: Database session
        current_user: Authenticated user

    Returns:
        Paginated events in descending timestamp order (most recent first)

    Raises:
        HTTPException: 404 if shipment not found
    """
    # Verify shipment exists
    shipment_exists = await db.execute(select(exists().where(Shipment.id == shipment_id)))
    if not shipment_exists.scalar():
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

    # Query audit log for shipment events
    query = (
        select(AuditLog)
        .where(
            and_(
                AuditLog.entity_type == "shipment",
                AuditLog.entity_id == shipment_id,
            )
        )
        .order_by(AuditLog.created_at.desc())
    )

    # Get total count
    count_query = (
        select(func.count())
        .select_from(AuditLog)
        .where(
            and_(
                AuditLog.entity_type == "shipment",
                AuditLog.entity_id == shipment_id,
            )
        )
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * size
    query = query.limit(size).offset(offset)

    result = await db.execute(query)
    audit_entries = result.scalars().all()

    # Convert to ShipmentEvent schema
    events = [
        ShipmentEvent(
            timestamp=entry.created_at,
            event_type=entry.action,
            description=entry.action,
            actor=entry.actor_name,
        )
        for entry in audit_entries
    ]

    total_pages = (total + size - 1) // size if total > 0 else 0

    return PaginatedResponse(
        items=events,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
    )


# ============================================================================
# Definitive Plan: GET /shipments/{id}/predict  (Phase 9 — new endpoint)
# ============================================================================


@router.get("/{shipment_id}/predict")
async def predict_shipment_delay(
    request: Request,
    shipment_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """ML delay prediction for one shipment (Plan §Phase 9).

    Uses the frozen ETA quantile model: P50 transit → delay vs the strictest
    SLA deadline. Falls back to the planned ETA (provenance=FALLBACK) when
    the registry is unavailable, never a 500.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select as _select

    from nexafreight.enums import LegStatus as _LegStatus
    from nexafreight.models import Location as _Location
    from nexafreight.models import Order as _Order
    from nexafreight.schemas.ops import ShipmentPredictResponse
    from nexafreight.services.sla_checker import compute_sla_risk

    shipment = await db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="shipment not found")
    await db.refresh(shipment, ["legs", "orders"])

    order = (
        (
            await db.execute(
                _select(_Order)
                .where(_Order.shipment_id == shipment_id)
                .order_by(_Order.sla_deadline)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    live_legs = [l for l in shipment.legs if str(l.status) != _LegStatus.REPLACED]
    total_km = sum(l.distance_km or 0.0 for l in live_legs)
    leg_count = max(1, len(live_legs))

    deadline = order.sla_deadline if order is not None else None
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)

    provenance = "FALLBACK"
    model_version: str | None = None
    p50_eta: datetime | None = None
    delay_p50_hours = 0.0

    # Registry shared app-wide at startup; absent in tests / degraded runs.
    registry = getattr(request.app.state, "ml_registry", None)

    if registry is not None and order is not None:
        try:
            eta_model = registry.get_eta_model()
            origin = await db.get(_Location, shipment.origin_id)
            destination = await db.get(_Location, shipment.destination_id)
            order_date = order.order_date or datetime.now(UTC)
            if order_date.tzinfo is None:
                order_date = order_date.replace(tzinfo=UTC)
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
                "order_country": (origin.country_code if origin else "US"),
                "customer_country": (destination.country_code if destination else "US"),
                "product_price": float(order.items[0].unit_price if order.items else order.revenue),
                "order_profit": float(order.revenue - order.shipping_cost),
                "sla_month": deadline.month if deadline else order_date.month,
                "sla_weekday": deadline.weekday() if deadline else order_date.weekday(),
                "sla_quarter": (
                    ((deadline.month - 1) // 3 + 1) if deadline else ((order_date.month - 1) // 3 + 1)
                ),
                "total_distance_km": total_km,
                "leg_count": leg_count,
            }
            prediction = eta_model.predict(features)
            model_version = getattr(registry, "eta_model_version", None)
            p50_eta = order_date + timedelta(days=float(prediction.p50_eta_days))
            provenance = "DERIVED"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Shipment predict ML path failed, using fallback: %s", exc)
            registry = None

    if p50_eta is None:
        # Fallback: latest planned arrival across live legs.
        if live_legs:
            latest = max(l.planned_arrival for l in live_legs)
            p50_eta = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
        else:
            p50_eta = datetime.now(UTC)
        model_version = None

    if deadline is not None and p50_eta > deadline:
        delay_p50_hours = (p50_eta - deadline).total_seconds() / 3600.0
    delay_p50_hours = max(delay_p50_hours, 0.0)

    risk = compute_sla_risk(deadline, p50_eta)
    return ShipmentPredictResponse(
        shipment_id=shipment_id,
        delay_p50_hours=round(delay_p50_hours, 2),
        sla_risk_level=str(risk),
        model_version=model_version,
        provenance=provenance,
    ).model_dump()


# ============================================================================
# Definitive Plan: GET /shipments/{id}/financials  (Phase 6 — new endpoint)
# ============================================================================


@router.get("/{shipment_id}/financials")
async def shipment_financials(
    shipment_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Per-shipment P&L snapshot (Plan §Phase 6).

    ADMIN / OPERATOR only — cost/margin visibility is restricted.
    """
    import math
    from datetime import UTC, datetime

    from nexafreight.enums import UserRole
    from nexafreight.schemas.ops import (
        FinancialOrderOut,
        PnlSnapshotOut,
        ShipmentFinancialsResponse,
    )
    from nexafreight.services.alert_engine import latest_planned_arrival
    from nexafreight.services.disruption_detector import TONNES_PER_CONTAINER
    from nexafreight.services.financial_engine import (
        CO2_G_PER_T_KM,
        SLA_PENALTY_PCT_PER_DAY,
        calculate_freight_cost,
        calculate_sla_penalty,
    calculate_sla_penalty_weekly,
        generate_pnl_snapshot,
    )

    if str(current_user.role) not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    shipment = await db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="shipment not found")
    await db.refresh(shipment, ["legs", "orders"])

    revenue = sum(o.revenue for o in shipment.orders)
    shipping = sum(o.shipping_cost for o in shipment.orders)

    eta = latest_planned_arrival(shipment)
    now = datetime.now(UTC)
    sla_penalty = 0.0
    if eta is not None:
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=UTC)
        for order in shipment.orders:
            deadline = order.sla_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if eta > deadline:
                days_late = max(1, math.ceil((eta - deadline).total_seconds() / 86400.0))
                sla_penalty += calculate_sla_penalty_weekly(
                    revenue=order.revenue,
                    pct_per_week=params.get_float("sla.penalty_pct_per_week", 0.5) / 100.0,
                    cap_pct=params.get_float("sla.penalty_cap_pct", 10.0) / 100.0,
                    days_late=days_late,
                )

    demurrage = 0.0
    dwell_days = max(0, (now - eta).days) if eta is not None else 0
    if dwell_days > 0:
        from nexafreight.services.financial_engine import (
            DEMURRAGE_FREE_DAYS,
            calculate_demurrage,
        )

        demurrage = calculate_demurrage(
            extra_days=dwell_days,
            free_days=int(params.get_int("demurrage.free_days", DEMURRAGE_FREE_DAYS)),
            daily_rate=params.get_float("demurrage.rate_inr_per_box_day", 5500.0)
            / params.get_float("fx.usd_inr", 88.0),
        ) * max(1, shipment.container_count)

    weight_t = max(1, shipment.container_count) * TONNES_PER_CONTAINER
    freight = 0.0
    carbon = 0.0
    for leg in shipment.legs:
        km = leg.distance_km or 0.0
        mode = str(leg.transport_mode)
        freight += calculate_freight_cost(km, weight_t, mode)
        co2_kg = leg.co2_kg
        if co2_kg is None:
            co2_kg = CO2_G_PER_T_KM.get(mode, CO2_G_PER_T_KM["SEA"]) * km * weight_t / 1000.0
        carbon += co2_kg * 0.08

    pnl = generate_pnl_snapshot(
        revenue_usd=revenue,
        shipping_cost_usd=shipping,
        sla_penalty_usd=sla_penalty,
        demurrage_usd=demurrage,
        freight_cost_usd=freight,
        carbon_cost_usd=carbon,
    )

    return ShipmentFinancialsResponse(
        shipment_id=shipment_id,
        container_count=max(1, shipment.container_count),
        container_weight_t=TONNES_PER_CONTAINER,
        orders=[
            FinancialOrderOut(
                order_number=o.order_number,
                revenue=o.revenue,
                shipping_cost=o.shipping_cost,
                sla_status=str(o.sla_status),
            )
            for o in shipment.orders
        ],
        pnl=PnlSnapshotOut(
            revenue_usd=round(pnl.revenue_usd, 2),
            shipping_cost_usd=round(pnl.shipping_cost_usd, 2),
            sla_penalty_usd=round(pnl.sla_penalty_usd, 2),
            demurrage_usd=round(pnl.demurrage_usd, 2),
            freight_cost_usd=round(pnl.freight_cost_usd, 2),
            carbon_cost_usd=round(pnl.carbon_cost_usd, 2),
            total_costs_usd=round(pnl.total_costs_usd, 2),
            margin_usd=round(pnl.margin_usd, 2),
            margin_pct=(round(pnl.margin_pct, 4) if pnl.margin_pct is not None else None),
            warnings=pnl.warnings,
        ),
        provenance="DERIVED",
    ).model_dump()
