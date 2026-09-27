"""Red Sea replay measurement core (Task 16, P1). scripts/24_red_sea_drill.py
is the CLI drill wrapper; this module is the importable measurer."""

from __future__ import annotations

from nexafreight.adapters.routing.sea_route import compute_sea_route

LANES: dict[str, tuple[float, float, float, float]] = {
    # lane: (lat_o, lon_o, lat_d, lon_d)
    "INJNP->NLRTM": (18.95, 72.95, 51.9225, 4.479),
    "INMUN->NLRTM": (22.74, 69.72, 51.9225, 4.479),
    "SGSIN->NLRTM": (1.29, 103.85, 51.9225, 4.479),
}
LANE_GROUP = {"INJNP->NLRTM": "india_eu", "INMUN->NLRTM": "india_eu", "SGSIN->NLRTM": "singapore_eu"}


def measure_ratios() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lane, (olat, olon, dlat, dlon) in LANES.items():
        normal = compute_sea_route(olat, olon, dlat, dlon, vessel_class="neo-panamax")
        cape = compute_sea_route(
            olat, olon, dlat, dlon, vessel_class="neo-panamax", restrictions=["suez"]
        )
        out[lane] = {
            "suez_nm": round(normal.distance_nm, 1),
            "cape_nm": round(cape.distance_nm, 1),
            "ratio": round(cape.distance_nm / normal.distance_nm, 4),
            "added_hours": round(max(0.0, (cape.duration_s - normal.duration_s) / 3600.0), 2),
        }
    return out
