"""Raw external-source events ingested nightly (wave 2)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from nexafreight.models.base import Base

class ExternalEvent(Base):
    __tablename__ = "external_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="REAL"
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_events_source_external_id"),
    )
