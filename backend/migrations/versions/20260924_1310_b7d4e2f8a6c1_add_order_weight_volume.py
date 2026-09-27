"""add order weight/volume for capacity-aware consolidation (task 21: E13)

Revision ID: b7d4e2f8a6c1
Revises: f9c3d7e2a8b1
Create Date: 2026-09-24 13:10:00

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d4e2f8a6c1"
down_revision = "f9c3d7e2a8b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("weight_kg", sa.Float(), nullable=True))
        batch.add_column(sa.Column("volume_m3", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("volume_m3")
        batch.drop_column("weight_kg")
