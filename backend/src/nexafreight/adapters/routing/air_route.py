"""Air routing adapter (geodesic arc)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from geopy.distance import geodesic  # type: ignore

from ._geometry import great_circle_geojson_str
from nexafreight.core import params

log = logging.getLogger("nexafreight.routing.air")



@dataclass
class AirRouteResult:
    geometry_geojson: str
    distance_km: float
    duration_s: float
    route_quality: str = "COMPUTED"


def compute_air_route(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    duration_hours: float | None = None,
) -> AirRouteResult:
    distance_km = geodesic((origin_lat, origin_lon), (dest_lat, dest_lon)).kilometers

    if duration_hours and duration_hours > 0:
        duration_s = duration_hours * 3600.0
    else:
        # Block time model: taxi + climb/descent + cruise
        taxi = params.get_float("air.taxi_hours", 0.3)
        climb_descent = params.get_float("air.climb_descent_hours", 0.4)
        cruise_speed = params.get_float("air.cruise_speed_kmh", 860.0)
        
        block_h = taxi + climb_descent + (distance_km / cruise_speed)
        duration_s = block_h * 3600.0

    geometry = great_circle_geojson_str(origin_lat, origin_lon, dest_lat, dest_lon)
    return AirRouteResult(
        geometry_geojson=geometry,
        distance_km=round(distance_km, 2),
        duration_s=round(duration_s, 1),
        route_quality="COMPUTED",
    )
