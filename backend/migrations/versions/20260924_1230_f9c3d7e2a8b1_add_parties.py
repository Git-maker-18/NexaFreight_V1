"""add parties + order party FKs (task 18: India demo world)

Revision ID: f9c3d7e2a8b1
Revises: e7a9f2b4c1d3
Create Date: 2026-09-24 12:30:00

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f9c3d7e2a8b1"
down_revision = "e7a9f2b4c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="IN"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_parties_name"),
    )
    op.create_index("ix_parties_name", "parties", ["name"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("shipper_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("consignee_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("carrier_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_orders_shipper_id_parties", "parties", ["shipper_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_orders_consignee_id_parties", "parties", ["consignee_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_orders_carrier_id_parties", "parties", ["carrier_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("fk_orders_carrier_id_parties", type_="foreignkey")
        batch.drop_constraint("fk_orders_consignee_id_parties", type_="foreignkey")
        batch.drop_constraint("fk_orders_shipper_id_parties", type_="foreignkey")
        batch.drop_column("carrier_id")
        batch.drop_column("consignee_id")
        batch.drop_column("shipper_id")
    op.drop_index("ix_parties_name", table_name="parties")
    op.drop_table("parties")
