"""Network graph models for multimodal route planning.

NetworkNode  — facility vertex (port, airport, rail terminal, ICD, road hub, river terminal).
NetworkEdge  — directed connection between two nodes for a specific transport mode.
EdgeSchedule — individual scheduled service on an edge (departure/arrival/capacity).
TransshipmentLink — transshipment rules and dwell times at a node.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexafreight.enums import NodeType, TransportMode
from nexafreight.models.base import Base
from nexafreight.models.mixins import TimestampMixin

if TYPE_CHECKING:
    pass


class NetworkNode(Base, TimestampMixin):
    """A logistics facility vertex in the multimodal network graph.

    Each node corresponds (optionally) to a Location row and carries information
    about which transport modes it can handle.
    """

    __tablename__ = "network_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    locode: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[NodeType] = mapped_column(String(30), nullable=False)
    # JSON list of supported TransportMode values, e.g. '["SEA","ROAD"]'
    modes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")

    # Relationships
    outbound_edges: Mapped[list[NetworkEdge]] = relationship(
        "NetworkEdge",
        foreign_keys="NetworkEdge.from_node_id",
        back_populates="from_node",
        cascade="all, delete-orphan",
    )
    inbound_edges: Mapped[list[NetworkEdge]] = relationship(
        "NetworkEdge",
        foreign_keys="NetworkEdge.to_node_id",
        back_populates="to_node",
    )
    transshipment_links: Mapped[list[TransshipmentLink]] = relationship(
        "TransshipmentLink",
        back_populates="node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        {"comment": "Multimodal logistics network nodes (facilities/hubs)"},
    )


class NetworkEdge(Base, TimestampMixin):
    """A directed transport link between two network nodes.

    mode-specific transit time is derived via a parameter key reference
    (e.g. 'rail.dfc.speed_kmh') rather than a hardcoded value.
    """

    __tablename__ = "network_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("network_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("network_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mode: Mapped[TransportMode] = mapped_column(String(20), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)

    # Parameter key references (values loaded via params module — invariant 2)
    transit_speed_param_key: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Key in parameter_empirical for the mode speed (e.g. rail.dfc.speed_kmh)"
    )
    base_cost_param_key: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Key in parameter_empirical for base cost rate (USD/tonne-km)"
    )
    co2_intensity_param_key: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Key in parameter_empirical for CO2 g/tonne-km"
    )

    # Physical constraints
    capacity_teu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reliability: Mapped[float] = mapped_column(Float, nullable=False, default=0.95,
        comment="Edge reliability 0..1 (probability service operates on schedule)"
    )
    is_dfc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
        comment="True for Dedicated Freight Corridor lanes"
    )

    # Relationships
    from_node: Mapped[NetworkNode] = relationship(
        "NetworkNode", foreign_keys=[from_node_id], back_populates="outbound_edges"
    )
    to_node: Mapped[NetworkNode] = relationship(
        "NetworkNode", foreign_keys=[to_node_id], back_populates="inbound_edges"
    )
    schedules: Mapped[list[EdgeSchedule]] = relationship(
        "EdgeSchedule",
        back_populates="edge",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        {"comment": "Directed multimodal transport links with parameter references"},
    )


class EdgeSchedule(Base):
    """One scheduled service instance on a network edge.

    Provenance: SIMULATED for seeded services, LIVE for real-time updates.
    """

    __tablename__ = "edge_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    edge_id: Mapped[int] = mapped_column(
        ForeignKey("network_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str] = mapped_column(String(20), nullable=False, default="SIMULATED")

    # Relationship
    edge: Mapped[NetworkEdge] = relationship("NetworkEdge", back_populates="schedules")

    __table_args__ = (
        {"comment": "Scheduled services on network edges (departure/arrival/capacity)"},
    )


class TransshipmentLink(Base):
    """Dwell and handling rules for cargo transfer at a network node.

    min_dwell_h / max_dwell_h bound the connection feasibility window.
    handling_cost_usd is the base transfer cost (USD per container).
    """

    __tablename__ = "transshipment_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("network_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_dwell_h: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    max_dwell_h: Mapped[float] = mapped_column(Float, nullable=False, default=72.0)
    handling_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=150.0)
    dg_capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reefer_capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationship
    node: Mapped[NetworkNode] = relationship("NetworkNode", back_populates="transshipment_links")

    __table_args__ = (
        {"comment": "Node-level transshipment dwell and handling capability"},
    )
