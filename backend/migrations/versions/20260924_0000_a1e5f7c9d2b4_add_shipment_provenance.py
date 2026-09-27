"""add shipment.provenance (audit E3)

Revision ID: a1e5f7c9d2b4
Revises: 3f8a2b1c9d4e
Create Date: 2026-09-24

Shipment was the only journey entity without ProvenanceMixin, so the active
demo world and the synthetic/parcel-era backfill (06_seed_analytics) were
indistinguishable to analytics queries — cumulative deadline windows mixed
eras forever. This column lets _active_world_filter() exclude non-active
provenances (default exclusion: HISTORICAL).
"""

from alembic import op
import sqlalchemy as sa


revision = "a1e5f7c9d2b4"
down_revision = "3f8a2b1c9d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shipments",
        sa.Column("provenance", sa.String(length=20), nullable=False,
                  server_default="SIMULATED"),
    )


def downgrade() -> None:
    op.drop_column("shipments", "provenance")
