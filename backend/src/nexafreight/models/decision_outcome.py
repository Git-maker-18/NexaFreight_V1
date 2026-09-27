"""Learnable outcome rows for decisions (Task 12, P1).

Every decision gets exactly one DecisionOutcome row, written at approval
time with the predicted picture frozen from the server-side option slate,
and completed by the finalizer once the shipment finishes (predicted vs
realized). This is the training substrate for preference learning (task 14)
and drift monitoring (task 13).

Honest scope of "realized" (v1): arrival delta vs the replaced plan and
penalties (SLA weekly norm) actually implied by the final arrival. Freight
and carbon deltas need per-leg cost telemetry that legs do not carry yet;
the columns exist and stay NULL until that telemetry lands.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nexafreight.models.base import Base
from nexafreight.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DecisionOutcome(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Predicted-vs-realized record for one decision (1:1, immutable core).

    Written in two phases:
      phase 1 (approval): predicted_* columns + recommended/override fields;
      phase 2 (shipment DELIVERED): realized_* columns by
      services.decision_outcome.finalize_decision_outcomes.
    """

    __tablename__ = "decision_outcomes"

    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    shipment_id: Mapped[str] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # What was chosen vs what the slate recommended
    chosen_option_key: Mapped[str] = mapped_column(String(50), nullable=False)
    recommended_option_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Set when chosen != recommended (auto-reason) or operator supplies one",
    )

    # Phase 1: predicted picture, frozen from the audited option snapshot
    predicted_total_impact_usd: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_cost_delta_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_sla_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_demurrage_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_carbon_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_revised_eta: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    baseline_planned_arrival: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Final planned arrival of the plan as it stood at decision time",
    )

    # Phase 2: realized picture (NULL until the shipment is DELIVERED)
    realized_arrival_delta_h: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Actual final arrival vs replaced plan's final planned arrival (+ = later)",
    )
    realized_penalty_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="SLA weekly-norm penalty implied by the actual arrival; demurrage v1 = 0",
    )
    realized_route_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_finalized_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
