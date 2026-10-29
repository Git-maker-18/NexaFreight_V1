"""relabel reconstructed legs and shipments provenance from REAL to DERIVED (ML-01)

Revision ID: e4f5a6b7c8d9
Revises: ca009891c5e2
Create Date: 2026-10-29 12:00:00

Reconstructed legs and historical shipments derived from DataCo / searoute /
geodesic interpolation are DERIVED, not REAL (which is strictly reserved for live telemetry).
"""

from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "ca009891c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update already-seeded reconstructed legs
    op.execute(
        sa.text("UPDATE legs SET provenance = 'DERIVED' WHERE provenance = 'REAL'")
    )
    # Update already-seeded shipments
    op.execute(
        sa.text("UPDATE shipments SET provenance = 'DERIVED' WHERE provenance = 'REAL'")
    )


def downgrade() -> None:
    pass
