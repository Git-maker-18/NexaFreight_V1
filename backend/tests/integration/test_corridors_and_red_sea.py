"""Tasks 20 + 16: measured VIA_CAPE corridor seeding and the Red Sea drill."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from nexafreight.models import CorridorAlternative
from nexafreight.services.corridor_seed import seed_corridors
from nexafreight.services.red_sea_drill import measure_ratios


@pytest.mark.asyncio
async def test_seed_corridors_upserts_single_measured_row(
    db_session, make_location
) -> None:
    await make_location(locode="INJNP", name="JNPT", country_code="IN", latitude=18.95, longitude=72.95)
    await make_location(locode="INMUN", name="Mundra", country_code="IN", latitude=22.74, longitude=69.72)
    await make_location(locode="SGSIN", name="Singapore", country_code="SG", latitude=1.29, longitude=103.85)
    await make_location(locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.9225, longitude=4.479)

    lanes = await seed_corridors(db_session)
    assert set(lanes) == {"INJNP->NLRTM", "INMUN->NLRTM", "SGSIN->NLRTM"}

    rows = (await db_session.execute(select(CorridorAlternative))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.option_key == "VIA_CAPE"
    assert row.cost_delta_factor == pytest.approx(lanes["INJNP->NLRTM"]["distance_ratio"], abs=0.01)
    assert row.time_delta_hours == pytest.approx(lanes["INJNP->NLRTM"]["added_hours"], abs=1.0)
    assert "PORT_CONGESTION" in row.applicable_disruption_types_json
    template = json.loads(row.route_template_json)
    assert template["legs"][0]["to"] == "DESTINATION"
    assert set(template["measured_lanes"]) == set(lanes)

    # Idempotent: re-seed must update, not duplicate.
    await seed_corridors(db_session)
    rows2 = (await db_session.execute(select(CorridorAlternative))).scalars().all()
    assert len(rows2) == 1


@pytest.mark.asyncio
async def test_seed_corridors_fresh_clone_upserts_missing_foreign_ports(
    db_session, make_location
) -> None:
    """Day-12b: a fresh clone lacks NLRTM/SGSIN (UN/LOCODE files are
    gitignored); seed_corridors must upsert them from the documented
    PORT_COORDS table instead of raising."""
    from nexafreight.models.location import Location
    from nexafreight.services.corridor_seed import PORT_COORDS

    # Fresh-clone world state: only the Indian endpoint locations exist.
    await make_location(locode="INJNP", name="JNPT", country_code="IN", latitude=18.95, longitude=72.95)
    await make_location(locode="INMUN", name="Mundra", country_code="IN", latitude=22.74, longitude=69.72)

    lanes = await seed_corridors(db_session)
    assert set(lanes) == {"INJNP->NLRTM", "INMUN->NLRTM", "SGSIN->NLRTM"}

    for locode in ("NLRTM", "SGSIN"):
        row = (
            await db_session.execute(select(Location).where(Location.locode == locode))
        ).scalar_one()
        name, country, lat, lon = PORT_COORDS[locode]
        assert row.name == name and row.country_code == country
        assert row.latitude == pytest.approx(lat)
        assert row.longitude == pytest.approx(lon)
    # Unknown locodes without fallback coordinates must still raise.
    from nexafreight.services import corridor_seed as cs

    saved = dict(cs.LANES)
    try:
        cs.LANES = {"XXNB->NLRTM": ("XXNB", "NLRTM")}
        with pytest.raises(RuntimeError, match="no fallback coordinates"):
            await seed_corridors(db_session)
    finally:
        cs.LANES = saved


@pytest.mark.asyncio
async def test_red_sea_ratios_within_pinned_bands() -> None:
    measured = measure_ratios()
    assert measured["INJNP->NLRTM"]["ratio"] == pytest.approx(1.70, abs=0.15)
    assert measured["INMUN->NLRTM"]["ratio"] == pytest.approx(1.74, abs=0.15)
    assert measured["SGSIN->NLRTM"]["ratio"] == pytest.approx(1.25, abs=0.08)
    # Cape detour must always add material time (the published 9-14 day story)
    assert measured["INJNP->NLRTM"]["added_hours"] > 100.0
