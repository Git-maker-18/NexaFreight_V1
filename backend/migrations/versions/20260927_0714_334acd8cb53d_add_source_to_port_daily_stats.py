"""add source to port_daily_stats

Revision ID: 334acd8cb53d
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27 07:14:42.258801+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '334acd8cb53d'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('port_daily_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=40), server_default='SIMULATED', nullable=False))

    # ### end Alembic commands ###


def downgrade() -> None:
    with op.batch_alter_table('port_daily_stats', schema=None) as batch_op:
        batch_op.drop_column('source')

    # ### end Alembic commands ###
