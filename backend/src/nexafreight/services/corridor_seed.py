"""Measured VIA_CAPE corridor seeding (Task 20, P1). Logic core;
scripts/23_seed_corridors.py is a thin CLI wrapper.

Measured via the searoute marine graph (24 Sep 2026): India-EU lanes gain
~1.70-1.74x distance via the Cape; Singapore-EU only ~1.25x (pre-gulf
gateway). The seeded row carries the representative India-EU factors plus
the full per-lane table inside route_template_json.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.adapters.routing.sea_route import compute_sea_route
from nexafreight.enums import DisruptionType, LocationType
from nexafreight.models import CorridorAlternative
from nexafreight.models.location import Location

LANES: dict[str, tuple[str, str]] = {
    "INJNP->NLRTM": ("INJNP", "NLRTM"),
    "INMUN->NLRTM": ("INMUN", "NLRTM"),
    "SGSIN->NLRTM": ("SGSIN", "NLRTM"),
}
VIA_CAPE_KEY = "VIA_CAPE"
REPRESENTATIVE_LANE = "INJNP->NLRTM"

#: UN/LOCODE coordinates for corridor endpoints. A FRESH clone's database
#: lacks the foreign ports: the UN/LOCODE ingest reads gitignored
#: data/raw files and the world builder only creates its own (Indian)
#: network nodes. These are the ingested reference coordinates (datahub
#: UN/LOCODE extract) -- identical to what pinned the cape_diversion
#: references, so measurements cannot drift. Missing locodes outside
#: this table still raise.
PORT_COORDS: dict[str, tuple[str, str, float, float]] = {
    "INJNP": ("JNPT (Jawaharlal Nehru Port Trust)", "IN", 18.949, 72.9519),
    "INMUN": ("Mundra Port", "IN", 22.7402, 69.7066),
    "NLRTM": ("Rotterdam", "NL", 51.916667, 4.5),
    "SGSIN": ("Singapore", "SG", 1.283333, 103.85),
}


def _measure(
    olat: float, olon: float, dlat: float, dlon: float
) -> tuple[float, float, float, float]:
    """Return (suez_nm, cape_nm, suez_h, cape_h) via the marine graph."""
    normal = compute_sea_route(olat, olon, dlat, dlon, vessel_class="neo-panamax")
    cape = compute_sea_route(
        olat, olon, dlat, dlon, vessel_class="neo-panamax", restrictions=["suez"]
    )
    return (
        normal.distance_nm,
        cape.distance_nm,
        normal.duration_s / 3600.0,
        cape.duration_s / 3600.0,
    )


async def seed_corridors(session: AsyncSession) -> dict[str, dict]:
    """Upsert the VIA_CAPE corridor from measured marine-graph numbers."""
    locations = {
        locode: (
            await session.execute(select(Location).where(Location.locode == locode))
        ).scalar_one_or_none()
        for locode in {code for lane in LANES.values() for code in lane}
    }
    missing = [key for key, value in locations.items() if value is None]
    # Fresh-clone safety (day-12b fix): upsert missing endpoints from the
    # documented PORT_COORDS table so a fresh clone can seed corridors
    # without the gitignored UN/LOCODE ingest files.
    for locode in missing:
        spec = PORT_COORDS.get(locode)
        if spec is None:
            raise RuntimeError(f"Missing locations (no fallback coordinates): {locode}")
        name, country, lat, lon = spec
        session.add(
            Location(
                locode=locode,
                name=name,
                country_code=country,
                location_type=LocationType.PORT,
                latitude=lat,
                longitude=lon,
            )
        )
    if missing:
        await session.flush()
        locations = {
            locode: (
                await session.execute(select(Location).where(Location.locode == locode))
            ).scalar_one()
            for locode in missing
        } | {k: v for k, v in locations.items() if v is not None}

    lane_table: dict[str, dict] = {}
    for lane_name, (o_code, d_code) in LANES.items():
        o, d = locations[o_code], locations[d_code]
        suez_nm, cape_nm, suez_h, cape_h = _measure(
            o.latitude, o.longitude, d.latitude, d.longitude
        )
        lane_table[lane_name] = {
            "suez_nm": round(suez_nm, 1),
            "cape_nm": round(cape_nm, 1),
            "suez_h": round(suez_h, 2),
            "cape_h": round(cape_h, 2),
            "distance_ratio": round(cape_nm / suez_nm, 4),
            "added_hours": round(max(0.0, cape_h - suez_h), 2),
        }

    rep = lane_table[REPRESENTATIVE_LANE]
    row = (
        await session.execute(
            select(CorridorAlternative).where(CorridorAlternative.option_key == VIA_CAPE_KEY)
        )
    ).scalar_one_or_none()
    if row is None:
        row = CorridorAlternative(option_key=VIA_CAPE_KEY)
        session.add(row)
    row.display_name = "Cape of Good Hope diversion (Suez unavailable)"
    row.applicable_disruption_types_json = json.dumps(
        [DisruptionType.PORT_CONGESTION.value, DisruptionType.WEATHER.value]
    )
    row.route_template_json = json.dumps(
        {
            "legs": [{"mode": "SEA", "to": "DESTINATION"}],
            "via": "Cape of Good Hope",
            "measured_lanes": lane_table,
            "representative_lane": REPRESENTATIVE_LANE,
        }
    )
    row.time_delta_hours = rep["added_hours"]
    row.cost_delta_factor = round(rep["distance_ratio"], 4)
    row.co2_delta_factor = round(rep["distance_ratio"], 4)
    await session.commit()
    return lane_table
