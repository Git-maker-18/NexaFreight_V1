"""Route plan persistence models.

RoutePlanRecord — a fully-scored multimodal itinerary for a shipment.
RouteLeg        — one segment within a route plan (mode + timing + KPIs).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexafreight.enums import PlanType, ShipmentPriority, TransportMode
from nexafreight.models.base import Base
from nexafreight.models.mixins import TimestampMixin

if TYPE_CHECKING:
    pass


class RoutePlanRecord(Base, TimestampMixin):
    """A scored multimodal route plan for a shipment.

    Multiple plans per shipment exist: INITIAL (auto), ALTERNATIVE (on-demand),
    RECOVERY (generated from current node after disruption).
    The recommended plan has recommended=True; others are alternatives.
    """

    __tablename__ = "route_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_type: Mapped[PlanType] = mapped_column(String(20), nullable=False)
    priority: Mapped[ShipmentPriority] = mapped_column(
        String(20), nullable=False, default=ShipmentPriority.STANDARD
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1,
        comment="1 = best (recommended), 2..k = alternatives"
    )
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Aggregate KPIs (DERIVED from leg rollups)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_time_h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_co2_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0,
        comment="Product of per-leg reliability (0..1)"
    )
    risk_index: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
        comment="Normalized composite risk (0..1)"
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
        comment="Weighted objective score (higher = better)"
    )

    # Human-readable rationale for recommendation
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Snapshot of objective weights used (JSON dict — for audit/replay)
    objective_weights_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Provenance of the plan computation
    provenance: Mapped[str] = mapped_column(String(20), nullable=False, default="DERIVED")

    # Relationships
    legs: Mapped[list[RouteLegRecord]] = relationship(
        "RouteLegRecord",
        back_populates="plan",
        order_by="RouteLegRecord.sequence_number",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        {"comment": "Scored multimodal route plans (INITIAL/ALTERNATIVE/RECOVERY)"},
    )


class RouteLegRecord(Base):
    """One leg in a scored route plan.

    References network_nodes for from/to, optionally references network_edges
    and edge_schedules for the concrete service used.
    """

    __tablename__ = "route_legs"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("route_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[TransportMode] = mapped_column(String(20), nullable=False)

    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("network_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("network_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    edge_id: Mapped[int | None] = mapped_column(
        ForeignKey("network_edges.id", ondelete="SET NULL"), nullable=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("edge_schedules.id", ondelete="SET NULL"), nullable=True
    )

    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Per-leg KPIs (provenance: DERIVED)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transit_h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    co2_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reliability: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    provenance: Mapped[str] = mapped_column(String(20), nullable=False, default="DERIVED")

    # Relationship
    plan: Mapped[RoutePlanRecord] = relationship("RoutePlanRecord", back_populates="legs")

    __table_args__ = (
        {"comment": "Individual legs within a scored route plan"},
    )
