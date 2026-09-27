"""Sea routing adapter with searoute-py and fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ._geometry import great_circle_geojson_str, haversine_nm
from nexafreight.core import params

log = logging.getLogger("nexafreight.routing.sea")


@dataclass
class SeaRouteResult:
    geometry_geojson: str
    distance_nm: float
    duration_s: float
    route_quality: str
    source: str


def compute_sea_route(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    vessel_class: str = "panamax",
    restrictions: list[str] | None = None,
) -> SeaRouteResult:
    # Speed table
    speeds = {
        "feeder": params.get_float("sea.speed.feeder", 15.0),
        "panamax": params.get_float("sea.speed.panamax", 19.0),
        "neo-panamax": params.get_float("sea.speed.neo_panamax", 21.0),
        "slow-steamed": params.get_float("sea.speed.slow_steamed", 17.0),
    }
    speed_knots = speeds.get(vessel_class, speeds["panamax"])

    try:
        import searoute as sr

        kwargs: dict = {"units": "naut"}
        if restrictions:
            kwargs["restrictions"] = restrictions

        route = sr.searoute(
            [origin_lon, origin_lat],
            [dest_lon, dest_lat],
            **kwargs,
        )
        geometry = json.dumps(route["geometry"])
        distance_nm = float(route["properties"]["length"])
        if distance_nm <= 0 or not geometry:
            raise ValueError("searoute returned empty geometry/distance")
        
        # Canal adder logic: only add if Suez canal is used and not restricted
        canal_adder_h = 0.0
        suez_restricted = restrictions and any("suez" in r.lower() for r in restrictions)
        if not suez_restricted and ("suez" in geometry.lower() or distance_nm > 5000):
            canal_adder_h = params.get_float("sea.canal_adder.suez_h", 14.0)

        duration_s = (distance_nm / speed_knots + canal_adder_h) * 3600.0

        return SeaRouteResult(
            geometry_geojson=geometry,
            distance_nm=round(distance_nm, 2),
            duration_s=round(duration_s, 1),
            route_quality="COMPUTED",
            source="SEAROUTE",
        )
    except Exception as exc:
        log.warning("searoute failed (%s); using great-circle APPROXIMATE fallback", exc)
        distance_nm = haversine_nm(origin_lat, origin_lon, dest_lat, dest_lon)
        duration_s = (distance_nm / speed_knots) * 3600.0
        geometry = great_circle_geojson_str(origin_lat, origin_lon, dest_lat, dest_lon)
        return SeaRouteResult(
            geometry_geojson=geometry,
            distance_nm=round(distance_nm, 2),
            duration_s=round(duration_s, 1),
            route_quality="APPROXIMATE",
            source="GREAT_CIRCLE_FALLBACK",
        )
