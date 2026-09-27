"""add decision_outcomes table (task 12: predicted-vs-realized logging)

Revision ID: e7a9f2b4c1d3
Revises: c7d9e1f3a5b6
Create Date: 2026-09-24 10:30:00

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7a9f2b4c1d3"
down_revision = "c7d9e1f3a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("chosen_option_key", sa.String(length=50), nullable=False),
        sa.Column("recommended_option_key", sa.String(length=50), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("predicted_total_impact_usd", sa.Float(), nullable=False),
        sa.Column("predicted_cost_delta_usd", sa.Float(), nullable=True),
        sa.Column("predicted_sla_usd", sa.Float(), nullable=True),
        sa.Column("predicted_demurrage_usd", sa.Float(), nullable=True),
        sa.Column("predicted_carbon_usd", sa.Float(), nullable=True),
        sa.Column("predicted_revised_eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_planned_arrival", sa.DateTime(timezone=True), nullable=True),
        sa.Column("realized_arrival_delta_h", sa.Float(), nullable=True),
        sa.Column("realized_penalty_usd", sa.Float(), nullable=True),
        sa.Column("realized_route_version", sa.Integer(), nullable=True),
        sa.Column("outcome_finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", name="uq_decision_outcomes_decision_id"),
    )
    op.create_index(
        "ix_decision_outcomes_shipment_id", "decision_outcomes", ["shipment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_decision_outcomes_shipment_id", table_name="decision_outcomes")
    op.drop_table("decision_outcomes")
