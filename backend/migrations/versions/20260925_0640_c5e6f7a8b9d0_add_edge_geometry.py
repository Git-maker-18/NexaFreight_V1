"""add network edge geometry cache (day-14: real road paths via ORS)

Revision ID: c5e6f7a8b9d0
Revises: b7d4e2f8a6c1
Create Date: 2026-09-25 06:40:00

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5e6f7a8b9d0"
down_revision = "b7d4e2f8a6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("network_edges") as batch:
        batch.add_column(sa.Column("geometry_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("network_edges") as batch:
        batch.drop_column("geometry_json")
