"""backfill GLEC v3.2 multimodal CO2 emission factors across legs and parameters (ML-03)

Revision ID: f7a8b9c0d1e2
Revises: e4f5a6b7c8d9
Create Date: 2026-10-29 13:00:00

Unifies all multimodal CO2 factors to GLEC Framework v3.2:
- SEA: 8.0 g/t-km (deep-sea container shipping weighted average 5k-10k TEU)
- ROAD: 62.0 g/t-km (heavy articulated diesel line-haul truck >32t)
- RAIL: 28.0 g/t-km (mixed electric/diesel freight train average)
- AIR: 602.0 g/t-km (dedicated air freighter average)

Recomputes legs.co2_kg from distance, container weight, and transport mode.
Updates parameter_empirical table records to match the unified factors.
"""

from alembic import op
import sqlalchemy as sa
import logging

revision = "f7a8b9c0d1e2"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

GLEC_FACTORS = {
    "SEA": 8.0,
    "ROAD": 62.0,
    "RAIL": 28.0,
    "AIR": 602.0,
}


def upgrade() -> None:
    # 1. Update parameter_empirical records if table exists
    for key, val in [
        ("co2.sea_g_per_tonne_km", "8.0"),
        ("co2.road_g_per_tonne_km", "62.0"),
        ("co2.rail_g_per_tonne_km", "28.0"),
        ("co2.air_g_per_tonne_km", "602.0"),
        ("co2.road_g_with_toll", "62.0"),
    ]:
        op.execute(
            sa.text(
                "UPDATE parameter_empirical SET value = :val WHERE key = :key"
            ).bindparams(val=val, key=key)
        )

    # 2. Recompute legs.co2_kg for each transport mode
    # Formula: (distance_km * factor * (container_count * 14.0 tonnes)) / 1000.0
    for mode, factor in GLEC_FACTORS.items():
        stmt = sa.text(
            f"""
            UPDATE legs
            SET co2_kg = ROUND(
                CAST(
                    (legs.distance_km * :factor * (
                        SELECT COALESCE(s.container_count, 1) * 14.0
                        FROM shipments s
                        WHERE s.id = legs.shipment_id
                    )) / 1000.0
                AS NUMERIC),
                3
            )
            WHERE legs.distance_km IS NOT NULL
              AND (legs.transport_mode = :mode OR legs.transport_mode LIKE '%{mode}')
            """
        ).bindparams(factor=factor, mode=mode)
        op.execute(stmt)


def downgrade() -> None:
    pass
