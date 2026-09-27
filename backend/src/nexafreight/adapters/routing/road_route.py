"""Road routing adapter using OpenRouteService with offline fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ._geometry import great_circle_geojson_str, haversine_km
from nexafreight.core import params

log = logging.getLogger("nexafreight.routing.road")


@dataclass
class RoadRouteResult:
    geometry_geojson: str
    distance_km: float
    duration_s: float
    route_quality: str = "COMPUTED"
    source: str = "OPENROUTESERVICE"


class RoadRouter:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._client = None
        if api_key:
            try:
                import openrouteservice  # type: ignore

                self._client = openrouteservice.Client(key=api_key)
            except Exception as exc:
                log.warning("Could not initialize openrouteservice client: %s", exc)

    def compute(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        corridor_class: str | None = None,
    ) -> RoadRouteResult:
        olat, olon = origin
        dlat, dlon = dest

        if self._client:
            try:
                # OpenRouteService expects coordinates in [lon, lat] order
                coords = [[olon, olat], [dlon, dlat]]
                routes = self._client.directions(
                    coordinates=coords,
                    profile="driving-hgv",
                    format="geojson",
                )
                features = routes.get("features", [])
                if features:
                    feat = features[0]
                    geom = json.dumps(feat.get("geometry", {}))
                    props = feat.get("properties", {}).get("summary", {})
                    dist_km = float(props.get("distance", 0.0)) / 1000.0
                    duration_s = float(props.get("duration", 0.0))
                    if dist_km > 0 and geom:
                        return RoadRouteResult(
                            geometry_geojson=geom,
                            distance_km=round(dist_km, 2),
                            duration_s=round(duration_s, 1),
                            route_quality="COMPUTED",
                            source="OPENROUTESERVICE",
                        )
            except Exception as exc:
                log.warning("OpenRouteService API call failed (%s); using road fallback", exc)

        # Fallback: Great-circle distance scaled by corridor or default road circuity factor
        direct_km = haversine_km(olat, olon, dlat, dlon)
        circ_key = f"road.circuity.{corridor_class}" if corridor_class else "road.circuity.default"
        circuity = params.get_float(circ_key)
        dist_km = direct_km * circuity
        speed_key = f"road.speed.{corridor_class}" if corridor_class else "road.speed.default"
        speed = params.get_float(speed_key)
        engine_h = (dist_km / speed) if speed > 0 else 0.0
        halt_rate = params.get_float("road.halt_allowance_h_per_4_5h", 0.75)
        halt_h = (engine_h / 4.5) * halt_rate if engine_h > 0 else 0.0
        duration_s = (engine_h + halt_h) * 3600.0
        geom = great_circle_geojson_str(olat, olon, dlat, dlon, n=16)

        return RoadRouteResult(
            geometry_geojson=geom,
            distance_km=round(dist_km, 2),
            duration_s=round(duration_s, 1),
            route_quality="APPROXIMATE",
            source="ROAD_FALLBACK",
        )
