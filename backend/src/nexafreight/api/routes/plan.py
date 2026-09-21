"""Multimodal route planning endpoint.

POST /api/v1/plan  — generate ranked alternative itineraries for a shipment.
GET  /api/v1/plan  — list persisted plans for a shipment.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.enums import PlanType, ShipmentPriority, UserRole
from nexafreight.models import Shipment, User
from nexafreight.models.route_plan import RouteLegRecord, RoutePlanRecord
from nexafreight.services.planner import ItineraryResult, get_planner

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    shipment_id: str
    priority: str = Field(default="STANDARD", description="CRITICAL|EXPRESS|STANDARD|ECONOMY")
    plan_type: str = Field(default="ALTERNATIVE", description="INITIAL|ALTERNATIVE|RECOVERY")
    deadline: datetime | None = Field(default=None, description="Hard deadline ISO8601")
    cargo_weight_kg: float = Field(default=15000.0, gt=0)
    origin_locode: str | None = Field(default=None, description="Override origin (e.g. recovery from mid-point)")
    seed: int | None = Field(default=None, description="RNG seed for deterministic output")


class LegKPIOut(BaseModel):
    sequence: int
    mode: str
    from_locode: str
    to_locode: str
    from_node_id: int
    to_node_id: int
    departure_at: str
    arrival_at: str
    transit_h: float
    cost_usd: float
    co2_kg: float
    reliability: float
    provenance: str


class RoutePlanOut(BaseModel):
    plan_id: int | None
    rank: int
    recommended: bool
    rationale: str
    priority: str
    plan_type: str
    total_cost_usd: float
    total_time_h: float
    total_co2_kg: float
    reliability_score: float
    risk_index: float
    score: float
    provenance: str
    legs: list[LegKPIOut]


class PlanResponse(BaseModel):
    shipment_id: str
    routes: list[RoutePlanOut]


def _itin_to_out(itin: ItineraryResult, plan_id: int | None = None) -> RoutePlanOut:
    legs_out = []
    for i, leg in enumerate(itin.legs, start=1):
        legs_out.append(LegKPIOut(
            sequence=i,
            mode=leg.mode,
            from_locode=leg.from_locode,
            to_locode=leg.to_locode,
            from_node_id=leg.from_node_id,
            to_node_id=leg.to_node_id,
            departure_at=leg.departure_at.isoformat(),
            arrival_at=leg.arrival_at.isoformat(),
            transit_h=leg.transit_h,
            cost_usd=leg.cost_usd,
            co2_kg=leg.co2_kg,
            reliability=leg.reliability,
            provenance=leg.provenance,
        ))
    return RoutePlanOut(
        plan_id=plan_id,
        rank=itin.rank,
        recommended=itin.recommended,
        rationale=itin.rationale,
        priority=itin.priority,
        plan_type=itin.plan_type,
        total_cost_usd=itin.total_cost_usd,
        total_time_h=itin.total_time_h,
        total_co2_kg=itin.total_co2_kg,
        reliability_score=itin.reliability_score,
        risk_index=itin.risk_index,
        score=itin.score,
        provenance="DERIVED",
        legs=legs_out,
    )


def _record_to_out(plan: RoutePlanRecord) -> RoutePlanOut:
    legs_out = []
    for leg in sorted(plan.legs, key=lambda l: l.sequence_number):
        legs_out.append(LegKPIOut(
            sequence=leg.sequence_number,
            mode=str(leg.mode),
            from_locode="",  # locode not stored on leg — could join but not critical for list view
            to_locode="",
            from_node_id=leg.from_node_id,
            to_node_id=leg.to_node_id,
            departure_at=leg.departure_at.isoformat(),
            arrival_at=leg.arrival_at.isoformat(),
            transit_h=leg.transit_h,
            cost_usd=leg.cost_usd,
            co2_kg=leg.co2_kg,
            reliability=leg.reliability,
            provenance=str(leg.provenance),
        ))
    return RoutePlanOut(
        plan_id=plan.id,
        rank=plan.rank,
        recommended=plan.recommended,
        rationale=plan.rationale or "",
        priority=str(plan.priority),
        plan_type=str(plan.plan_type),
        total_cost_usd=plan.total_cost_usd,
        total_time_h=plan.total_time_h,
        total_co2_kg=plan.total_co2_kg,
        reliability_score=plan.reliability_score,
        risk_index=plan.risk_index,
        score=plan.score,
        provenance=str(plan.provenance),
        legs=legs_out,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=PlanResponse, summary="Generate ranked route plans for a shipment")
async def create_route_plan(
    body: PlanRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PlanResponse:
    """Generate (and persist) ranked multimodal route alternatives for a shipment.

    Requires OPERATOR or ADMIN role. Returns up to 5 ranked itineraries scored
    by the priority weight profile. The recommended route (rank=1) is marked with
    a rationale string.

    All KPIs carry DERIVED or SIMULATED provenance tags.
    """
    # Role check
    if str(current_user.role) not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Operator or Admin role required")

    # Validate priority and plan_type
    try:
        priority = ShipmentPriority(body.priority.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid priority: {body.priority}")

    try:
        plan_type = PlanType(body.plan_type.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid plan_type: {body.plan_type}")

    # Load shipment to resolve origin/dest locodes
    shipment = (
        await db.execute(
            select(Shipment)
            .where(Shipment.id == body.shipment_id)
            .options(
                selectinload(Shipment.origin),
                selectinload(Shipment.destination),
            )
        )
    ).scalar_one_or_none()
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"Shipment {body.shipment_id} not found")

    origin = await shipment.awaitable_attrs.origin
    dest = await shipment.awaitable_attrs.destination

    # Allow override for recovery routing
    origin_locode = body.origin_locode or (origin.locode if origin else None)
    dest_locode = dest.locode if dest else None

    if not origin_locode or not dest_locode:
        raise HTTPException(status_code=422, detail="Shipment missing origin or destination")

    planner = get_planner()
    try:
        itineraries = await planner.plan(
            session=db,
            shipment_id=body.shipment_id,
            origin_locode=origin_locode,
            dest_locode=dest_locode,
            priority=priority,
            plan_type=plan_type,
            deadline=body.deadline,
            cargo_weight_kg=body.cargo_weight_kg,
            seed=body.seed,
            persist=True,
        )
    except Exception as exc:
        logger.exception("Planner error for shipment %s: %s", body.shipment_id, exc)
        raise HTTPException(status_code=500, detail=f"Planner error: {exc}") from exc

    routes = [_itin_to_out(itin) for itin in itineraries]
    return PlanResponse(shipment_id=body.shipment_id, routes=routes)


@router.get("", response_model=PlanResponse, summary="List persisted route plans for a shipment")
async def list_route_plans(
    shipment_id: str = Query(..., description="Shipment UUID"),
    plan_type: str | None = Query(None, description="Filter by plan type"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PlanResponse:
    """List previously persisted route plans for a shipment.

    Returns all plan records ordered by rank (best first) within each plan_type.
    Provenance: DERIVED for all KPI fields.
    """
    stmt = (
        select(RoutePlanRecord)
        .where(RoutePlanRecord.shipment_id == shipment_id)
        .options(selectinload(RoutePlanRecord.legs))
        .order_by(RoutePlanRecord.rank)
    )
    if plan_type:
        try:
            pt = PlanType(plan_type.upper())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid plan_type: {plan_type}")
        stmt = stmt.where(RoutePlanRecord.plan_type == pt)

    plans = (await db.execute(stmt)).scalars().all()
    routes = [_record_to_out(plan) for plan in plans]
    return PlanResponse(shipment_id=shipment_id, routes=routes)
