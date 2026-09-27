"""add missing unique index on position_reports (E24)

Revision ID: c7d9e1f3a5b6
Revises: a1e5f7c9d2b4
Create Date: 2026-09-24

The PositionReport MODEL declares UniqueConstraint(leg_id, reported_at)
(uq_position_reports_leg_reported_at), but migration 001 never created it —
model/DB skew. The position interpolator's upsert (ON CONFLICT (leg_id,
reported_at)) fails on SQLite/Postgres without it: every simulated position
write errored and the live map stayed empty (found live in the demo world).

Note for long-lived databases: creating a UNIQUE index fails if duplicates
exist. The demo/CI databases are clean; operators of production databases
should dedupe (keep max(id) per (leg_id, reported_at)) before upgrading.
"""

from alembic import op


revision = "c7d9e1f3a5b6"
down_revision = "a1e5f7c9d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ALTER ADD CONSTRAINT — batch mode rebuilds the table
    # (works on both SQLite and Postgres).
    with op.batch_alter_table("position_reports") as batch:
        batch.create_unique_constraint(
            "uq_position_reports_leg_reported_at",
            ["leg_id", "reported_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("position_reports") as batch:
        batch.drop_constraint(
            "uq_position_reports_leg_reported_at", type_="unique"
        )
