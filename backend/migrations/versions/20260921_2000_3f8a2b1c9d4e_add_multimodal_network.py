"""Add multimodal network tables and seed India network

Revision ID: 3f8a2b1c9d4e
Revises: 8420d96dacf5
Create Date: 2026-09-21 20:00:00.000000

Creates:
  - network_nodes
  - network_edges
  - edge_schedules
  - transshipment_links
  - route_plans
  - route_legs

Seeds:
  - 35 India network nodes (ports, airports, rail terminals, ICDs, road hubs)
  - ~110 network edges
  - ~120 scheduled services
  - transshipment link rules
  - parameter_empirical + parameter_policy entries for planner
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f8a2b1c9d4e"
down_revision: str | None = "8420d96dacf5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)


def _dt(days: int, hours: int = 0) -> str:
    """Return ISO datetime string offset from base date."""
    from datetime import timedelta
    d = _BASE + timedelta(days=days, hours=hours)
    return d.isoformat()


# ---------------------------------------------------------------------------
# Node definitions (locode, name, node_type, modes_json, lat, lon, country)
# Locode must be unique — using facility-specific codes for airports/ICDs.
# ---------------------------------------------------------------------------
_NODES = [
    # === SEA PORTS (6) ===
    ("INJNP", "JNPT (Jawaharlal Nehru Port Trust)", "PORT",       '["SEA","ROAD"]',            18.9490,  72.9519, "IN"),
    ("INMUN", "Mundra Port",                         "PORT",       '["SEA","ROAD","RAIL"]',     22.7402,  69.7066, "IN"),
    ("INMAA", "Chennai Port",                        "PORT",       '["SEA","ROAD","RAIL"]',     13.0825,  80.2867, "IN"),
    ("INVTZ", "Vizag (Visakhapatnam) Port",          "PORT",       '["SEA","ROAD"]',            17.6868,  83.2185, "IN"),
    ("INCCU", "Kolkata-Haldia Port",                 "PORT",       '["SEA","ROAD","RAIL"]',     22.5726,  88.3639, "IN"),
    ("INCOK", "Cochin (Kochi) Port",                 "PORT",       '["SEA","ROAD"]',            9.9312,   76.2673, "IN"),
    # === AIRPORTS (6) ===
    ("INDEL", "Delhi Indira Gandhi International Airport", "AIRPORT", '["AIR","ROAD"]',          28.5562,  77.1000, "IN"),
    ("INBOM", "Mumbai Chhatrapati Shivaji Airport",        "AIRPORT", '["AIR","ROAD"]',          19.0896,  72.8656, "IN"),
    ("INBLR", "Bengaluru Kempegowda Airport",             "AIRPORT", '["AIR","ROAD"]',          13.1986,  77.7066, "IN"),
    ("INMAA2","Chennai Airport (MAA)",                    "AIRPORT", '["AIR","ROAD"]',          12.9941,  80.1709, "IN"),
    ("INHYD", "Hyderabad Rajiv Gandhi Airport",           "AIRPORT", '["AIR","ROAD"]',          17.2403,  78.4294, "IN"),
    ("INCCUA","Kolkata Netaji Subhash Bose Airport",      "AIRPORT", '["AIR","ROAD"]',          22.6520,  88.4463, "IN"),
    # === ICD / RAIL TERMINALS (11) ===
    ("INTKG", "Tughlakabad ICD (Delhi)",             "ICD",        '["RAIL","ROAD"]',           28.4924,  77.2797, "IN"),
    ("INDAD", "Dadri ICD (Greater Noida)",           "ICD",        '["RAIL","ROAD"]',           28.5600,  77.5500, "IN"),
    ("INCHK", "Chakeri ICD (Kanpur)",                "ICD",        '["RAIL","ROAD"]',           26.4499,  80.3319, "IN"),
    ("INSUB", "Subedarganj ICD (Prayagraj)",         "ICD",        '["RAIL","ROAD"]',           25.3928,  81.8742, "IN"),
    ("INLUD", "Ludhiana Rail Terminal",              "RAIL_TERMINAL", '["RAIL","ROAD"]',        30.9010,  75.8573, "IN"),
    ("INKWG", "Kathuwas ICD (Rajasthan)",            "ICD",        '["RAIL","ROAD"]',           27.9500,  76.4500, "IN"),
    ("INVNS", "Varanasi IWT Terminal (NW-1)",        "RIVER_TERMINAL",'["ROAD","RAIL"]',        25.3176,  82.9739, "IN"),
    ("INSAH", "Sahibganj IWT Terminal (NW-1)",       "RIVER_TERMINAL",'["ROAD"]',              24.9850,  87.6750, "IN"),
    ("INHAL", "Haldia IWT Terminal (NW-1)",          "RIVER_TERMINAL",'["SEA","ROAD"]',         22.0255,  88.0585, "IN"),
    ("INKAG", "Kalughat IWT Terminal (NW-1)",        "RIVER_TERMINAL",'["ROAD"]',              25.6000,  85.1500, "IN"),
    ("INPTN", "Patna Rail Hub",                      "RAIL_TERMINAL",'["RAIL","ROAD"]',        25.5941,  85.1376, "IN"),
    # === ROAD HUBS (13) ===
    ("INDLH", "Delhi NCR Road Hub",                  "ROAD_HUB",   '["ROAD"]',                 28.6139,  77.2090, "IN"),
    ("INMUM", "Mumbai Road Hub",                     "ROAD_HUB",   '["ROAD"]',                 19.0760,  72.8777, "IN"),
    ("INPUN", "Pune Road Hub",                       "ROAD_HUB",   '["ROAD"]',                 18.5204,  73.8567, "IN"),
    ("INAHM", "Ahmedabad Road Hub",                  "ROAD_HUB",   '["ROAD"]',                 23.0225,  72.5714, "IN"),
    ("INSUR", "Surat Road Hub",                      "ROAD_HUB",   '["ROAD"]',                 21.1702,  72.8311, "IN"),
    ("INBLH", "Bangalore Road Hub",                  "ROAD_HUB",   '["ROAD"]',                 12.9716,  77.5946, "IN"),
    ("INCHE", "Chennai Road Hub",                    "ROAD_HUB",   '["ROAD"]',                 13.0827,  80.2707, "IN"),
    ("INHYA", "Hyderabad Road Hub",                  "ROAD_HUB",   '["ROAD"]',                 17.3850,  78.4867, "IN"),
    ("INKAL", "Kolkata Road Hub",                    "ROAD_HUB",   '["ROAD"]',                 22.5726,  88.3639, "IN"),
    ("INNAG", "Nagpur Road Hub",                     "ROAD_HUB",   '["ROAD"]',                 21.1458,  79.0882, "IN"),
    ("INJPR", "Jaipur Road Hub",                     "ROAD_HUB",   '["ROAD"]',                 26.9124,  75.7873, "IN"),
    ("INLUH", "Ludhiana Road Hub",                   "ROAD_HUB",   '["ROAD"]',                 30.9010,  75.8573, "IN"),
    ("INCBE", "Coimbatore Road Hub",                 "ROAD_HUB",   '["ROAD"]',                 11.0168,  76.9558, "IN"),
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return _haversine_km(lat1, lon1, lat2, lon2) / 1.852


# ---------------------------------------------------------------------------
# Edge definitions
# (from_locode, to_locode, mode, distance_km_override_or_None,
#  speed_param_key, cost_param_key, co2_param_key, reliability, is_dfc, cap_teu)
# distance_km_override=None → computed from haversine with road circuity for ROAD
# ---------------------------------------------------------------------------
_EDGES_RAW = [
    # ── SEA lanes (ocean loops — distances from searoute approximation) ──
    # JNPT ↔ Mundra (coastal feeder)
    ("INJNP", "INMUN", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.95, False, 500),
    ("INMUN", "INJNP", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.95, False, 500),
    # JNPT ↔ Cochin
    ("INJNP", "INCOK", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.92, False, 500),
    ("INCOK", "INJNP", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.92, False, 500),
    # JNPT ↔ Chennai
    ("INJNP", "INMAA", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.92, False, 2000),
    ("INMAA", "INJNP", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.92, False, 2000),
    # JNPT ↔ Vizag
    ("INJNP", "INVTZ", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.90, False, 1500),
    ("INVTZ", "INJNP", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.90, False, 1500),
    # JNPT ↔ Kolkata
    ("INJNP", "INCCU", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.88, False, 1500),
    ("INCCU", "INJNP", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.88, False, 1500),
    # Chennai ↔ Vizag
    ("INMAA", "INVTZ", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.93, False, 500),
    ("INVTZ", "INMAA", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.93, False, 500),
    # Chennai ↔ Kolkata
    ("INMAA", "INCCU", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.88, False, 1000),
    ("INCCU", "INMAA", "SEA",   None, "sea.panamax.speed_kn", "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.88, False, 1000),
    # Mundra ↔ Cochin
    ("INMUN", "INCOK", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.91, False, 500),
    ("INCOK", "INMUN", "SEA",   None, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.91, False, 500),
    # Haldia ↔ Kolkata (NW-1 short feeder)
    ("INHAL", "INCCU", "SEA",   50.0, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.80, False, 100),
    ("INCCU", "INHAL", "SEA",   50.0, "sea.feeder.speed_kn",  "sea.cost_usd_per_nm", "co2.sea_g_per_tonne_km", 0.80, False, 100),

    # ── DFC RAIL lanes (Western DFC: Mundra-Delhi via Rewari; Eastern DFC: Delhi-Kolkata) ──
    # Western DFC: Mundra → Kathuwas → Tughlakabad (Delhi)
    ("INMUN", "INKWG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.92, True, 1000),
    ("INKWG", "INMUN", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.92, True, 1000),
    ("INKWG", "INTKG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.93, True, 1000),
    ("INTKG", "INKWG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.93, True, 1000),
    # Mundra → Dadri (Western DFC direct)
    ("INMUN", "INDAD", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.91, True, 1000),
    ("INDAD", "INMUN", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.91, True, 1000),
    # JNPT → Tughlakabad (JNPT connector to W-DFC)
    ("INJNP", "INTKG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 800),
    ("INTKG", "INJNP", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 800),
    # Eastern DFC: Tughlakabad → Kolkata
    ("INTKG", "INCCU", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 800),
    ("INCCU", "INTKG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 800),
    # Ludhiana → Tughlakabad (DFC extension)
    ("INLUD", "INTKG", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.91, True, 600),
    ("INTKG", "INLUD", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.91, True, 600),
    # Ludhiana → Mundra (W-DFC via Kathuwas)
    ("INLUD", "INMUN", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 600),
    ("INMUN", "INLUD", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.90, True, 600),
    # Ludhiana → JNPT direct DFC
    ("INLUD", "INJNP", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.89, True, 500),
    ("INJNP", "INLUD", "RAIL",  None, "rail.dfc.speed_kmh",   "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.89, True, 500),

    # ── Conventional RAIL ──
    # Subedarganj (Allahabad) ↔ Kolkata
    ("INSUB", "INCCU", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.75, False, 400),
    ("INCCU", "INSUB", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.75, False, 400),
    # Chakeri (Kanpur) ↔ Delhi
    ("INCHK", "INTKG", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.76, False, 400),
    ("INTKG", "INCHK", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.76, False, 400),
    # Chennai ↔ Bangalore rail
    ("INMAA", "INBLR", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.80, False, 400),
    ("INBLR", "INMAA", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.80, False, 400),
    # Patna ↔ Kolkata
    ("INPTN", "INCCU", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.78, False, 400),
    ("INCCU", "INPTN", "RAIL",  None, "rail.conventional.speed_kmh", "rail.cost_usd_per_km", "co2.rail_g_per_tonne_km", 0.78, False, 400),

    # ── AIR cargo lanes ──
    ("INDEL", "INBOM", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INBOM", "INDEL", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INDEL", "INBLR", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INBLR", "INDEL", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INDEL", "INMAA2","AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),
    ("INMAA2","INDEL", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),
    ("INDEL", "INHYD", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INHYD", "INDEL", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INDEL", "INCCUA","AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),
    ("INCCUA","INDEL", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),
    ("INBOM", "INBLR", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INBLR", "INBOM", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INBOM", "INMAA2","AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INMAA2","INBOM", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INHYD", "INBLR", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INBLR", "INHYD", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.97, False, None),
    ("INHYD", "INCCUA","AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),
    ("INCCUA","INHYD", "AIR",  None, "air.cruise_speed_kmh", "air.cost_usd_per_km", "co2.air_g_per_tonne_km", 0.96, False, None),

    # ── ROAD connections (ports/airports ↔ road hubs; key drayage links) ──
    # JNPT ↔ Mumbai road hub
    ("INJNP", "INMUM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    ("INMUM", "INJNP", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    # Mumbai airport ↔ Mumbai road hub
    ("INBOM", "INMUM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    ("INMUM", "INBOM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    # JNPT ↔ Pune road hub
    ("INJNP", "INPUN", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_with_toll", 0.85, False, None),
    ("INPUN", "INJNP", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_with_toll", 0.85, False, None),
    # Mundra ↔ Ahmedabad
    ("INMUN", "INAHM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    ("INAHM", "INMUN", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    # Mundra ↔ Surat
    ("INMUN", "INSUR", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    ("INSUR", "INMUN", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    # Delhi airport ↔ Delhi NCR road hub
    ("INDEL", "INDLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    ("INDLH", "INDEL", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    # Delhi NCR ↔ Tughlakabad ICD (drayage)
    ("INDLH", "INTKG", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    ("INTKG", "INDLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    # Delhi NCR ↔ Dadri ICD
    ("INDLH", "INDAD", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    ("INDAD", "INDLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    # Ludhiana road hub ↔ Ludhiana rail terminal
    ("INLUH", "INLUD", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.92, False, None),
    ("INLUD", "INLUH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.92, False, None),
    # Ludhiana ↔ Delhi NCR road
    ("INLUH", "INDLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    ("INDLH", "INLUH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    # Chennai port ↔ Chennai road hub
    ("INMAA", "INCHE", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    ("INCHE", "INMAA", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    # Chennai airport ↔ Chennai road hub
    ("INMAA2","INCHE", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    ("INCHE", "INMAA2","ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.90, False, None),
    # Bangalore airport ↔ Bangalore road hub
    ("INBLR", "INBLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    ("INBLH", "INBLR", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    # Hyderabad airport ↔ Hyderabad road hub
    ("INHYD", "INHYA", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    ("INHYA", "INHYD", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.88, False, None),
    # Kolkata port ↔ Kolkata road hub
    ("INCCU", "INKAL", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    ("INKAL", "INCCU", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    # Kolkata airport ↔ Kolkata road hub
    ("INCCUA","INKAL", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    ("INKAL", "INCCUA","ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.87, False, None),
    # Cochin port ↔ Coimbatore road hub
    ("INCOK", "INCBE", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    ("INCBE", "INCOK", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    # Nagpur ↔ Mumbai / Hyderabad (logistics hub crossroads)
    ("INNAG", "INMUM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.83, False, None),
    ("INMUM", "INNAG", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.83, False, None),
    ("INNAG", "INHYA", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.83, False, None),
    ("INHYA", "INNAG", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.83, False, None),
    # Jaipur ↔ Delhi
    ("INJPR", "INDLH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    ("INDLH", "INJPR", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.85, False, None),
    # Jaipur ↔ Ahmedabad
    ("INJPR", "INAHM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.84, False, None),
    ("INAHM", "INJPR", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.84, False, None),
    # Ahmedabad ↔ Mumbai
    ("INAHM", "INMUM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    ("INMUM", "INAHM", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.86, False, None),
    # NW-1 river terminals ↔ road hubs (road drayage to river)
    ("INVNS", "INCHK", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.82, False, None),
    ("INCHK", "INVNS", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.82, False, None),
    ("INSAH", "INPTN", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.82, False, None),
    ("INPTN", "INSAH", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.82, False, None),
    ("INKAG", "INPTN", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.80, False, None),
    ("INPTN", "INKAG", "ROAD", None, "road.speed_kmh", "road.cost_usd_per_km", "co2.road_g_per_tonne_km", 0.80, False, None),
]

# ---------------------------------------------------------------------------
# Parameter seeds
# ---------------------------------------------------------------------------
_NOW = datetime.fromisoformat("2026-09-21T00:00:00+00:00")

_EMPIRICAL_PARAMS = [
    # Rail speeds (empirical, DFC design spec + actual averages)
    ("rail.dfc.speed_kmh",       "57.5",  "km/h",   "Indian Railways DFC Speed Specification 2024", _NOW,
     "Average of WDFC (58 km/h) and EDFC (57 km/h) design speeds", 100, None, None),
    ("rail.conventional.speed_kmh","21.5","km/h",   "Indian Railways Annual Statistical Statement 2023", _NOW,
     "Average freight train speed on non-DFC lines 2022-23", 5000, None, None),
    # Sea speeds (knots)
    ("sea.feeder.speed_kn",      "15.0",  "kn",     "UNCTAD Maritime Review 2023", _NOW,
     "Typical coastal feeder vessel speed India coastal trade", 200, None, None),
    ("sea.panamax.speed_kn",     "19.0",  "kn",     "UNCTAD Maritime Review 2023", _NOW,
     "Panamax vessel typical service speed", 500, None, None),
    ("sea.neo_panamax.speed_kn", "21.0",  "kn",     "UNCTAD Maritime Review 2023", _NOW,
     "Neo-Panamax vessel typical service speed", 300, None, None),
    ("sea.slow_steamed.speed_kn","17.0",  "kn",     "UNCTAD Maritime Review 2023", _NOW,
     "Panamax slow-steaming speed (fuel economy mode)", 200, None, None),
    # Sea cost per nm (USD, approximate bulk container rate)
    ("sea.cost_usd_per_nm",      "0.12",  "USD/nm/TEU", "Drewry Container Market Insight Q2 2026", _NOW,
     "Average Indian coastal trade TEU freight rate per nautical mile", 1000, None, None),
    # Air
    ("air.cruise_speed_kmh",     "860.0", "km/h",   "IATA Air Cargo Market Statistics 2024", _NOW,
     "Typical B747-8F cruising speed at FL380", 100, None, None),
    ("air.taxi_hours",           "0.3",   "h",       "IATA Ground Handling Manual", _NOW,
     "Standard taxi time both ends per flight", 50, None, None),
    ("air.climb_descent_hours",  "0.4",   "h",       "IATA Air Cargo Market Statistics 2024", _NOW,
     "Climb + descent time added to cruise segment", 50, None, None),
    ("air.handling_hours",       "12.0",  "h",       "IATA CEIV Pharma Standard", _NOW,
     "Air cargo ground handling + customs clearance buffer", 200, None, None),
    ("air.cost_usd_per_km",      "4.50",  "USD/km/tonne", "IATA Air Cargo Market Statistics 2024 – India lanes", _NOW,
     "Average air cargo rate per tonne-km on India domestic lanes", 500, None, None),
    # Road
    ("road.speed_kmh",           "48.0",  "km/h",   "National Highways Authority of India Average 2023", _NOW,
     "Average truck speed on NH/state highway with circuity", 5000, None, None),
    ("road.circuity.default",    "1.35",  "ratio",   "NHAI Road Length Statistics 2023", _NOW,
     "Ratio of actual road distance to great-circle for typical India lanes", 1000, None, None),
    ("road.cost_usd_per_km",     "0.065", "USD/km/tonne", "FFFAI India Trucking Survey 2024", _NOW,
     "Average FTL truck freight rate per tonne-km on NH", 2000, None, None),
    # Rail cost
    ("rail.cost_usd_per_km",     "0.025", "USD/km/tonne", "Indian Railways Freight Rate Schedule 2024", _NOW,
     "Average containerized freight rate per tonne-km", 3000, None, None),
    # CO2 emission factors (GLEC Framework v3)
    ("co2.sea_g_per_tonne_km",   "6.5",   "gCO2/t-km", "GLEC Framework v3 2023", _NOW,
     "Container shipping WTW emission factor (gCO2e per tonne-km)", 10000, None, None),
    ("co2.air_g_per_tonne_km",   "500.0", "gCO2/t-km", "GLEC Framework v3 2023", _NOW,
     "Air freight WTW emission factor (gCO2e per tonne-km)", 10000, None, None),
    ("co2.road_g_per_tonne_km",  "62.0",  "gCO2/t-km", "GLEC Framework v3 2023", _NOW,
     "Road freight WTW emission factor for diesel HGV India (gCO2e per tonne-km)", 10000, None, None),
    ("co2.road_g_with_toll",     "65.0",  "gCO2/t-km", "GLEC Framework v3 2023", _NOW,
     "Road freight with tolled expressway routing (slightly higher avg speed, same fuel)", 5000, None, None),
    ("co2.rail_g_per_tonne_km",  "22.0",  "gCO2/t-km", "GLEC Framework v3 2023", _NOW,
     "Rail freight WTW emission factor India diesel traction (gCO2e per tonne-km)", 10000, None, None),
    # Suez canal transit data (for reroute delta)
    ("sea.canal_adder.suez_h",   "14.0",  "h",       "Suez Canal Authority Transit Statistics 2023", _NOW,
     "Average Suez Canal transit time including anchorage", 5000, None, None),
    ("sea.suez_reroute_extra_nm","2058.0","nm",       "IMO Circular 2024 Cape Route Analysis", _NOW,
     "Extra nautical miles via Cape of Good Hope vs Suez (Europe-Asia standard lane)", 100, None, None),
]

_POLICY_PARAMS = [
    # Planner configuration
    ("planner.connection_margin_h", "2.0",   "h",   "nexafreight-ops",
     "Minimum buffer hours added to declared dwell minimum to allow connection feasibility; accounts for irregular service arrivals"),
    ("planner.top_k",               "5",     None,  "nexafreight-ops",
     "Maximum number of alternative route plans returned per planning query"),
    ("planner.horizon_days",        "14",    "days","nexafreight-ops",
     "Maximum number of future days to search for schedule departures in the time-expanded graph"),
    # Objective weight profiles by priority (sum must ≈ 1.0 per profile)
    # CRITICAL: speed dominates
    ("plan.weight.CRITICAL.cost",        "0.10", None, "nexafreight-ops",
     "CRITICAL priority: cost objective weight (speed-first profile)"),
    ("plan.weight.CRITICAL.time",        "0.60", None, "nexafreight-ops",
     "CRITICAL priority: transit time objective weight"),
    ("plan.weight.CRITICAL.reliability", "0.20", None, "nexafreight-ops",
     "CRITICAL priority: reliability objective weight"),
    ("plan.weight.CRITICAL.co2",         "0.05", None, "nexafreight-ops",
     "CRITICAL priority: CO2 objective weight"),
    ("plan.weight.CRITICAL.risk",        "0.05", None, "nexafreight-ops",
     "CRITICAL priority: risk index objective weight"),
    # EXPRESS: speed + reliability
    ("plan.weight.EXPRESS.cost",         "0.20", None, "nexafreight-ops",
     "EXPRESS priority: cost objective weight"),
    ("plan.weight.EXPRESS.time",         "0.45", None, "nexafreight-ops",
     "EXPRESS priority: transit time objective weight"),
    ("plan.weight.EXPRESS.reliability",  "0.20", None, "nexafreight-ops",
     "EXPRESS priority: reliability objective weight"),
    ("plan.weight.EXPRESS.co2",          "0.10", None, "nexafreight-ops",
     "EXPRESS priority: CO2 objective weight"),
    ("plan.weight.EXPRESS.risk",         "0.05", None, "nexafreight-ops",
     "EXPRESS priority: risk index objective weight"),
    # STANDARD: balanced
    ("plan.weight.STANDARD.cost",        "0.40", None, "nexafreight-ops",
     "STANDARD priority: cost objective weight (balanced profile)"),
    ("plan.weight.STANDARD.time",        "0.25", None, "nexafreight-ops",
     "STANDARD priority: transit time objective weight"),
    ("plan.weight.STANDARD.reliability", "0.20", None, "nexafreight-ops",
     "STANDARD priority: reliability objective weight"),
    ("plan.weight.STANDARD.co2",         "0.10", None, "nexafreight-ops",
     "STANDARD priority: CO2 objective weight"),
    ("plan.weight.STANDARD.risk",        "0.05", None, "nexafreight-ops",
     "STANDARD priority: risk index objective weight"),
    # ECONOMY: cost dominates
    ("plan.weight.ECONOMY.cost",         "0.60", None, "nexafreight-ops",
     "ECONOMY priority: cost objective weight (cost-first profile)"),
    ("plan.weight.ECONOMY.time",         "0.10", None, "nexafreight-ops",
     "ECONOMY priority: transit time objective weight"),
    ("plan.weight.ECONOMY.reliability",  "0.15", None, "nexafreight-ops",
     "ECONOMY priority: reliability objective weight"),
    ("plan.weight.ECONOMY.co2",          "0.10", None, "nexafreight-ops",
     "ECONOMY priority: CO2 objective weight"),
    ("plan.weight.ECONOMY.risk",         "0.05", None, "nexafreight-ops",
     "ECONOMY priority: risk index objective weight"),
]


def upgrade() -> None:
    """Create multimodal network tables and seed India network."""
    import math

    # ── 1. Create tables ──────────────────────────────────────────────────

    op.create_table(
        "network_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("locode", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=30), nullable=False),
        sa.Column("modes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="IN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_network_nodes")),
        sa.UniqueConstraint("locode", name=op.f("uq_network_nodes_locode")),
        comment="Multimodal logistics network nodes (facilities/hubs)",
    )
    op.create_index(op.f("ix_network_nodes_locode"), "network_nodes", ["locode"], unique=True)

    op.create_table(
        "network_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("transit_speed_param_key", sa.String(length=100), nullable=False),
        sa.Column("base_cost_param_key", sa.String(length=100), nullable=False),
        sa.Column("co2_intensity_param_key", sa.String(length=100), nullable=False),
        sa.Column("capacity_teu", sa.Integer(), nullable=True),
        sa.Column("reliability", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("is_dfc", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["from_node_id"], ["network_nodes.id"],
            name=op.f("fk_network_edges_from_node_id_network_nodes"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_node_id"], ["network_nodes.id"],
            name=op.f("fk_network_edges_to_node_id_network_nodes"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_network_edges")),
        comment="Directed multimodal transport links with parameter references",
    )
    op.create_index(op.f("ix_network_edges_from_node_id"), "network_edges", ["from_node_id"])
    op.create_index(op.f("ix_network_edges_to_node_id"), "network_edges", ["to_node_id"])

    op.create_table(
        "edge_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("edge_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capacity_remaining", sa.Integer(), nullable=True),
        sa.Column("provenance", sa.String(length=20), nullable=False, server_default="SIMULATED"),
        sa.ForeignKeyConstraint(["edge_id"], ["network_edges.id"],
            name=op.f("fk_edge_schedules_edge_id_network_edges"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edge_schedules")),
        comment="Scheduled services on network edges (departure/arrival/capacity)",
    )
    op.create_index(op.f("ix_edge_schedules_edge_id"), "edge_schedules", ["edge_id"])
    op.create_index(op.f("ix_edge_schedules_departure_at"), "edge_schedules", ["departure_at"])

    op.create_table(
        "transshipment_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("min_dwell_h", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("max_dwell_h", sa.Float(), nullable=False, server_default="72.0"),
        sa.Column("handling_cost_usd", sa.Float(), nullable=False, server_default="150.0"),
        sa.Column("dg_capable", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("reefer_capable", sa.Boolean(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["node_id"], ["network_nodes.id"],
            name=op.f("fk_transshipment_links_node_id_network_nodes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transshipment_links")),
        comment="Node-level transshipment dwell and handling capability",
    )
    op.create_index(op.f("ix_transshipment_links_node_id"), "transshipment_links", ["node_id"])

    op.create_table(
        "route_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("plan_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="STANDARD"),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_time_h", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_co2_kg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reliability_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("risk_index", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("objective_weights_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("provenance", sa.String(length=20), nullable=False, server_default="DERIVED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"],
            name=op.f("fk_route_plans_shipment_id_shipments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_plans")),
        comment="Scored multimodal route plans (INITIAL/ALTERNATIVE/RECOVERY)",
    )
    op.create_index(op.f("ix_route_plans_shipment_id"), "route_plans", ["shipment_id"])

    op.create_table(
        "route_legs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.Column("edge_id", sa.Integer(), nullable=True),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("transit_h", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("co2_kg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reliability", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("provenance", sa.String(length=20), nullable=False, server_default="DERIVED"),
        sa.ForeignKeyConstraint(["plan_id"], ["route_plans.id"],
            name=op.f("fk_route_legs_plan_id_route_plans"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_node_id"], ["network_nodes.id"],
            name=op.f("fk_route_legs_from_node_id_network_nodes"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_node_id"], ["network_nodes.id"],
            name=op.f("fk_route_legs_to_node_id_network_nodes"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["edge_id"], ["network_edges.id"],
            name=op.f("fk_route_legs_edge_id_network_edges"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["schedule_id"], ["edge_schedules.id"],
            name=op.f("fk_route_legs_schedule_id_edge_schedules"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_legs")),
        comment="Individual legs within a scored route plan",
    )
    op.create_index(op.f("ix_route_legs_plan_id"), "route_legs", ["plan_id"])

    # ── 2. Seed parameters ────────────────────────────────────────────────

    conn = op.get_bind()

    # Empirical parameters
    for key, value, unit, source, as_of, derivation, sample_count, valid_from, valid_to in _EMPIRICAL_PARAMS:
        conn.execute(
            sa.text(
                "INSERT INTO parameter_empirical "
                "(key, value, unit, source, as_of, derivation_method, sample_count, valid_from, valid_to) "
                "VALUES (:key, :value, :unit, :source, :as_of, :derivation_method, :sample_count, :valid_from, :valid_to) "
                "ON CONFLICT(key) DO NOTHING"
            ),
            {
                "key": key, "value": value, "unit": unit, "source": source,
                "as_of": as_of, "derivation_method": derivation,
                "sample_count": sample_count, "valid_from": valid_from, "valid_to": valid_to,
            },
        )

    # Policy parameters
    for key, value, unit, owner, rationale in _POLICY_PARAMS:
        conn.execute(
            sa.text(
                "INSERT INTO parameter_policy (key, value, unit, owner, rationale) "
                "VALUES (:key, :value, :unit, :owner, :rationale) "
                "ON CONFLICT(key) DO NOTHING"
            ),
            {"key": key, "value": value, "unit": unit, "owner": owner, "rationale": rationale},
        )

    # ── 3. Seed network nodes ─────────────────────────────────────────────

    node_id_by_locode: dict[str, int] = {}
    now_str = datetime.fromisoformat("2026-09-21T00:00:00+00:00")
    for locode, name, node_type, modes_json, lat, lon, country in _NODES:
        res = conn.execute(
            sa.text(
                "INSERT INTO network_nodes (locode, name, node_type, modes_json, latitude, longitude, country_code, created_at, updated_at) "
                "VALUES (:locode, :name, :node_type, :modes_json, :lat, :lon, :country, :now, :now) "
                "ON CONFLICT(locode) DO NOTHING"
            ),
            {"locode": locode, "name": name, "node_type": node_type, "modes_json": modes_json,
             "lat": lat, "lon": lon, "country": country, "now": now_str},
        )

    # Re-fetch all node ids
    rows = conn.execute(sa.text("SELECT id, locode FROM network_nodes")).fetchall()
    for row in rows:
        node_id_by_locode[row[1]] = row[0]

    # ── 4. Seed transshipment links ───────────────────────────────────────
    _TRANSSHIPMENT = [
        # (locode, min_dwell_h, max_dwell_h, handling_cost_usd, dg_capable, reefer_capable)
        ("INJNP",  8.0,  48.0, 200.0, False, True),
        ("INMUN",  6.0,  48.0, 180.0, True,  True),
        ("INMAA",  8.0,  48.0, 200.0, False, True),
        ("INVTZ",  8.0,  48.0, 180.0, False, False),
        ("INCCU",  12.0, 72.0, 220.0, False, False),
        ("INCOK",  6.0,  48.0, 170.0, False, True),
        ("INDEL",  4.0,  24.0, 350.0, True,  True),   # Airport: faster turnaround
        ("INBOM",  4.0,  24.0, 350.0, True,  True),
        ("INBLR",  4.0,  24.0, 300.0, False, True),
        ("INMAA2", 4.0,  24.0, 300.0, False, False),
        ("INHYD",  4.0,  24.0, 280.0, False, False),
        ("INCCUA", 4.0,  24.0, 280.0, False, False),
        ("INTKG",  4.0,  48.0, 100.0, True,  False),  # ICD: efficient
        ("INDAD",  4.0,  48.0, 100.0, True,  False),
        ("INCHK",  6.0,  72.0, 120.0, False, False),
        ("INSUB",  6.0,  72.0, 120.0, False, False),
        ("INLUD",  4.0,  48.0, 90.0,  False, False),
        ("INKWG",  6.0,  72.0, 110.0, False, False),
        ("INVNS",  24.0, 120.0, 80.0, False, False),  # River terminal: slow
        ("INSAH",  24.0, 120.0, 80.0, False, False),
        ("INHAL",  12.0, 72.0,  90.0, False, False),
        ("INKAG",  24.0, 120.0, 80.0, False, False),
        ("INPTN",  6.0,  72.0, 100.0, False, False),
    ]
    for locode, min_dwell, max_dwell, cost, dg, reefer in _TRANSSHIPMENT:
        nid = node_id_by_locode.get(locode)
        if nid is None:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO transshipment_links (node_id, min_dwell_h, max_dwell_h, handling_cost_usd, dg_capable, reefer_capable) "
                "VALUES (:node_id, :min_dwell, :max_dwell, :cost, :dg, :reefer)"
            ),
            {"node_id": nid, "min_dwell": min_dwell, "max_dwell": max_dwell,
             "cost": cost, "dg": dg, "reefer": reefer},
        )

    # ── 5. Seed edges (compute distances from haversine) ─────────────────

    node_coords: dict[str, tuple[float, float]] = {
        locode: (lat, lon) for locode, _, _, _, lat, lon, _ in _NODES
    }

    edge_id_by_pair: dict[tuple[str, str, str], int] = {}

    for from_loc, to_loc, mode, dist_override, speed_key, cost_key, co2_key, reliability, is_dfc, cap_teu in _EDGES_RAW:
        from_id = node_id_by_locode.get(from_loc)
        to_id = node_id_by_locode.get(to_loc)
        if from_id is None or to_id is None:
            continue

        if dist_override is not None:
            dist_km = dist_override
        else:
            from_lat, from_lon = node_coords[from_loc]
            to_lat, to_lon = node_coords[to_loc]
            raw_km = _haversine_km(from_lat, from_lon, to_lat, to_lon)
            # Apply road circuity factor for ROAD edges
            if mode == "ROAD":
                raw_km = raw_km * 1.35
            elif mode == "SEA":
                # Sea: use haversine_nm * 1.852 but add 15% for coastal routing
                raw_nm = _haversine_nm(from_lat, from_lon, to_lat, to_lon)
                raw_km = raw_nm * 1.852 * 1.15
            dist_km = round(raw_km, 1)

        cap_val = cap_teu if cap_teu is not None else "NULL"
        res = conn.execute(
            sa.text(
                "INSERT INTO network_edges "
                "(from_node_id, to_node_id, mode, distance_km, transit_speed_param_key, "
                "base_cost_param_key, co2_intensity_param_key, capacity_teu, reliability, is_dfc, created_at, updated_at) "
                "VALUES (:from_id, :to_id, :mode, :dist_km, :speed_key, :cost_key, :co2_key, "
                ":cap_teu, :reliability, :is_dfc, :now, :now) RETURNING id"
            ),
            {
                "from_id": from_id, "to_id": to_id, "mode": mode, "dist_km": dist_km,
                "speed_key": speed_key, "cost_key": cost_key, "co2_key": co2_key,
                "cap_teu": cap_teu, "reliability": reliability, "is_dfc": bool(is_dfc),
                "now": now_str,
            },
        )
        edge_id = res.scalar_one()
        if edge_id:
            edge_id_by_pair[(from_loc, to_loc, mode)] = edge_id

    # ── 6. Seed scheduled services ────────────────────────────────────────
    # Generate recurring schedules for the next 14 days from base date.
    # SEA: weekly; RAIL DFC: daily; RAIL conv: 3x/week; AIR: daily/2x daily; ROAD: rolling

    schedules: list[dict] = []

    def _add_sched(from_loc: str, to_loc: str, mode: str, service_name: str,
                   dep_day: int, dep_hour: int, transit_h: float, cap: int, prov: str = "SIMULATED") -> None:
        key = (from_loc, to_loc, mode)
        eid = edge_id_by_pair.get(key)
        if eid is None:
            return
        dep = _BASE + __import__("datetime").timedelta(days=dep_day, hours=dep_hour)
        arr = dep + __import__("datetime").timedelta(hours=transit_h)
        cutoff = dep - __import__("datetime").timedelta(hours=24)
        schedules.append({
            "edge_id": eid,
            "service_name": service_name,
            "departure_at": dep,
            "arrival_at": arr,
            "cutoff_at": cutoff,
            "capacity_remaining": cap,
            "provenance": prov,
        })

    # SEA schedules (weekly loops)
    for week_day in [0, 7]:  # 2 sailings over 14-day window
        _add_sched("INJNP", "INMUN", "SEA", "JNPT-MUN-W1", week_day, 10, 20.0, 350)
        _add_sched("INMUN", "INJNP", "SEA", "MUN-JNPT-W1", week_day+1, 8, 20.0, 350)
        _add_sched("INJNP", "INCOK", "SEA", "JNPT-COK-W1", week_day, 14, 50.0, 300)
        _add_sched("INCOK", "INJNP", "SEA", "COK-JNPT-W1", week_day+2, 8, 50.0, 300)
        _add_sched("INJNP", "INMAA", "SEA", "JNPT-MAA-W1", week_day, 16, 72.0, 800)
        _add_sched("INMAA", "INJNP", "SEA", "MAA-JNPT-W1", week_day+3, 10, 72.0, 800)
        _add_sched("INJNP", "INVTZ", "SEA", "JNPT-VTZ-W1", week_day+1, 10, 96.0, 600)
        _add_sched("INVTZ", "INJNP", "SEA", "VTZ-JNPT-W1", week_day+4, 12, 96.0, 600)
        _add_sched("INJNP", "INCCU", "SEA", "JNPT-CCU-W1", week_day, 20, 168.0, 600)
        _add_sched("INCCU", "INJNP", "SEA", "CCU-JNPT-W1", week_day+7, 8, 168.0, 600)
        _add_sched("INMAA", "INVTZ", "SEA", "MAA-VTZ-W1", week_day+2, 14, 30.0, 200)
        _add_sched("INVTZ", "INMAA", "SEA", "VTZ-MAA-W1", week_day+3, 8, 30.0, 200)
        _add_sched("INMAA", "INCCU", "SEA", "MAA-CCU-W1", week_day+1, 18, 120.0, 500)
        _add_sched("INCCU", "INMAA", "SEA", "CCU-MAA-W1", week_day+5, 8, 120.0, 500)
        _add_sched("INMUN", "INCOK", "SEA", "MUN-COK-W1", week_day+1, 16, 40.0, 200)
        _add_sched("INCOK", "INMUN", "SEA", "COK-MUN-W1", week_day+2, 14, 40.0, 200)

    # RAIL DFC daily schedules
    for day in range(14):
        hour = 6 if day % 2 == 0 else 18  # alternating departures
        _add_sched("INLUD", "INJNP", "RAIL", "DFC-LUD-JNPT-D", day, hour, 40.0, 250)
        _add_sched("INJNP", "INLUD", "RAIL", "DFC-JNPT-LUD-D", day, hour+4, 40.0, 250)
        _add_sched("INLUD", "INMUN", "RAIL", "DFC-LUD-MUN-D",  day, hour, 36.0, 250)
        _add_sched("INMUN", "INLUD", "RAIL", "DFC-MUN-LUD-D",  day, hour+2, 36.0, 250)
        _add_sched("INLUD", "INTKG", "RAIL", "DFC-LUD-TKG-D",  day, hour, 6.0, 300)
        _add_sched("INTKG", "INLUD", "RAIL", "DFC-TKG-LUD-D",  day, hour+1, 6.0, 300)
        _add_sched("INTKG", "INJNP", "RAIL", "DFC-TKG-JNPT-D", day, 8, 34.0, 300)
        _add_sched("INJNP", "INTKG", "RAIL", "DFC-JNPT-TKG-D", day, 22, 34.0, 300)
        _add_sched("INMUN", "INTKG", "RAIL", "DFC-MUN-TKG-D",  day, 6, 30.0, 400)
        _add_sched("INTKG", "INMUN", "RAIL", "DFC-TKG-MUN-D",  day, 18, 30.0, 400)
        _add_sched("INMUN", "INDAD", "RAIL", "DFC-MUN-DAD-D",  day, 8, 29.0, 400)
        _add_sched("INDAD", "INMUN", "RAIL", "DFC-DAD-MUN-D",  day, 20, 29.0, 400)
        _add_sched("INKWG", "INTKG", "RAIL", "DFC-KWG-TKG-D",  day, 10, 8.0,  300)
        _add_sched("INTKG", "INKWG", "RAIL", "DFC-TKG-KWG-D",  day, 20, 8.0,  300)
        _add_sched("INMUN", "INKWG", "RAIL", "DFC-MUN-KWG-D",  day, 6, 22.0, 400)
        _add_sched("INKWG", "INMUN", "RAIL", "DFC-KWG-MUN-D",  day, 18, 22.0, 400)
        _add_sched("INTKG", "INCCU", "RAIL", "DFC-TKG-CCU-D",  day, 6, 30.0, 300)
        _add_sched("INCCU", "INTKG", "RAIL", "DFC-CCU-TKG-D",  day, 18, 30.0, 300)

    # RAIL conventional (3x/week)
    for day in [0, 3, 7, 10]:
        _add_sched("INSUB", "INCCU", "RAIL", "CONV-SUB-CCU", day, 8, 48.0, 150)
        _add_sched("INCCU", "INSUB", "RAIL", "CONV-CCU-SUB", day+2, 14, 48.0, 150)
        _add_sched("INCHK", "INTKG", "RAIL", "CONV-CHK-TKG", day, 10, 24.0, 150)
        _add_sched("INTKG", "INCHK", "RAIL", "CONV-TKG-CHK", day+1, 8, 24.0, 150)
        _add_sched("INMAA", "INBLR", "RAIL", "CONV-MAA-BLR", day, 6, 10.0, 200)
        _add_sched("INBLR", "INMAA", "RAIL", "CONV-BLR-MAA", day, 20, 10.0, 200)
        _add_sched("INPTN", "INCCU", "RAIL", "CONV-PTN-CCU", day, 12, 16.0, 150)
        _add_sched("INCCU", "INPTN", "RAIL", "CONV-CCU-PTN", day+1, 6, 16.0, 150)

    # AIR cargo lanes (2x daily for key lanes)
    for day in range(14):
        for hour in [8, 20]:  # morning and night freighters
            _add_sched("INDEL", "INBOM", "AIR", f"AI-DEL-BOM-{hour}", day, hour, 2.5, 30)
            _add_sched("INBOM", "INDEL", "AIR", f"AI-BOM-DEL-{hour}", day, hour, 2.5, 30)
            _add_sched("INDEL", "INBLR", "AIR", f"AI-DEL-BLR-{hour}", day, hour, 3.0, 25)
            _add_sched("INBLR", "INDEL", "AIR", f"AI-BLR-DEL-{hour}", day, hour, 3.0, 25)
        # Single flight for other pairs
        _add_sched("INDEL", "INMAA2","AIR", f"AI-DEL-MAA-D{day}", day, 10, 3.5, 20)
        _add_sched("INMAA2","INDEL", "AIR", f"AI-MAA-DEL-D{day}", day, 16, 3.5, 20)
        _add_sched("INDEL", "INHYD", "AIR", f"AI-DEL-HYD-D{day}", day, 9, 3.0, 20)
        _add_sched("INHYD", "INDEL", "AIR", f"AI-HYD-DEL-D{day}", day, 17, 3.0, 20)
        _add_sched("INDEL", "INCCUA","AIR", f"AI-DEL-CCU-D{day}", day, 11, 3.0, 20)
        _add_sched("INCCUA","INDEL", "AIR", f"AI-CCU-DEL-D{day}", day, 16, 3.0, 20)
        _add_sched("INBOM", "INBLR", "AIR", f"AI-BOM-BLR-D{day}", day, 9, 1.5, 15)
        _add_sched("INBLR", "INBOM", "AIR", f"AI-BLR-BOM-D{day}", day, 15, 1.5, 15)
        _add_sched("INBOM", "INMAA2","AIR", f"AI-BOM-MAA-D{day}", day, 8, 1.75, 15)
        _add_sched("INMAA2","INBOM", "AIR", f"AI-MAA-BOM-D{day}", day, 14, 1.75, 15)
        _add_sched("INHYD", "INBLR", "AIR", f"AI-HYD-BLR-D{day}", day, 10, 1.0, 10)
        _add_sched("INBLR", "INHYD", "AIR", f"AI-BLR-HYD-D{day}", day, 14, 1.0, 10)
        _add_sched("INHYD", "INCCUA","AIR", f"AI-HYD-CCU-D{day}", day, 12, 2.0, 10)
        _add_sched("INCCUA","INHYD", "AIR", f"AI-CCU-HYD-D{day}", day, 16, 2.0, 10)

    # ROAD schedules (rolling daily — represents truck departure windows)
    for day in range(14):
        for hour in [6, 12, 18]:  # 3 departure windows/day
            _add_sched("INJNP", "INMUM", "ROAD", f"TRK-JNPT-MUM-H{hour}",  day, hour, 4.0,  50)
            _add_sched("INMUM", "INJNP", "ROAD", f"TRK-MUM-JNPT-H{hour}",  day, hour, 4.0,  50)
            _add_sched("INMUN", "INAHM", "ROAD", f"TRK-MUN-AHM-H{hour}",   day, hour, 4.5,  50)
            _add_sched("INAHM", "INMUN", "ROAD", f"TRK-AHM-MUN-H{hour}",   day, hour, 4.5,  50)
            _add_sched("INDLH", "INLUH", "ROAD", f"TRK-DLH-LUH-H{hour}",   day, hour, 7.0,  50)
            _add_sched("INLUH", "INDLH", "ROAD", f"TRK-LUH-DLH-H{hour}",   day, hour, 7.0,  50)
            _add_sched("INDLH", "INTKG", "ROAD", f"TRK-DLH-TKG-H{hour}",   day, hour, 1.5,  80)
            _add_sched("INTKG", "INDLH", "ROAD", f"TRK-TKG-DLH-H{hour}",   day, hour, 1.5,  80)
            _add_sched("INMAA", "INCHE", "ROAD", f"TRK-MAA-CHE-H{hour}",   day, hour, 1.0, 100)
            _add_sched("INCHE", "INMAA", "ROAD", f"TRK-CHE-MAA-H{hour}",   day, hour, 1.0, 100)
            _add_sched("INBLR", "INBLH", "ROAD", f"TRK-BLR-BLH-H{hour}",  day, hour, 1.5,  80)
            _add_sched("INBLH", "INBLR", "ROAD", f"TRK-BLH-BLR-H{hour}",  day, hour, 1.5,  80)
            _add_sched("INCCU", "INKAL", "ROAD", f"TRK-CCU-KAL-H{hour}",   day, hour, 1.5,  60)
            _add_sched("INKAL", "INCCU", "ROAD", f"TRK-KAL-CCU-H{hour}",   day, hour, 1.5,  60)
            _add_sched("INLUD", "INLUH", "ROAD", f"TRK-LUD-LUH-H{hour}",   day, hour, 0.5, 100)
            _add_sched("INLUH", "INLUD", "ROAD", f"TRK-LUH-LUD-H{hour}",   day, hour, 0.5, 100)
            _add_sched("INJNP", "INPUN", "ROAD", f"TRK-JNPT-PUN-H{hour}",  day, hour, 5.0,  50)
            _add_sched("INPUN", "INJNP", "ROAD", f"TRK-PUN-JNPT-H{hour}",  day, hour, 5.0,  50)

    for sched in schedules:
        conn.execute(
            sa.text(
                "INSERT INTO edge_schedules "
                "(edge_id, service_name, departure_at, arrival_at, cutoff_at, capacity_remaining, provenance) "
                "VALUES (:edge_id, :service_name, :departure_at, :arrival_at, :cutoff_at, :capacity_remaining, :provenance)"
            ),
            sched,
        )


def downgrade() -> None:
    """Drop all multimodal network tables in reverse FK order."""
    op.drop_index(op.f("ix_route_legs_plan_id"), table_name="route_legs")
    op.drop_table("route_legs")

    op.drop_index(op.f("ix_route_plans_shipment_id"), table_name="route_plans")
    op.drop_table("route_plans")

    op.drop_index(op.f("ix_transshipment_links_node_id"), table_name="transshipment_links")
    op.drop_table("transshipment_links")

    op.drop_index(op.f("ix_edge_schedules_departure_at"), table_name="edge_schedules")
    op.drop_index(op.f("ix_edge_schedules_edge_id"), table_name="edge_schedules")
    op.drop_table("edge_schedules")

    op.drop_index(op.f("ix_network_edges_to_node_id"), table_name="network_edges")
    op.drop_index(op.f("ix_network_edges_from_node_id"), table_name="network_edges")
    op.drop_table("network_edges")

    op.drop_index(op.f("ix_network_nodes_locode"), table_name="network_nodes")
    op.drop_table("network_nodes")
