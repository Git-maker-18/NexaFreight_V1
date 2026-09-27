"""Database models for governed and empirical parameters."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from nexafreight.models.base import Base


class ParameterPolicy(Base):
    """Business governance choices (thresholds, cooldowns, approval limits)."""

    __tablename__ = "parameter_policy"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ParameterEmpirical(Base):
    """Claims about the real world (speeds, dwells, ratios)."""

    __tablename__ = "parameter_empirical"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    derivation_method: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
