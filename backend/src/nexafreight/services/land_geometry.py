"""Land-edge geometry (day-14): real road paths from ORS, stored on edges.

Design (mirrors the day-12d sea-lane pattern):
- geometry belongs on the *edge* (stable entity), computed once and
  cached; legs inherit it at materialization time.
- ORS `driving-hgv` profile for road edges; the API key comes from
  settings (`ors_api_key`). Free tier is 2,000 req/day — the fill script
  only touches edges that lack geometry and sleeps politely between
  calls, so repeated runs are cheap.
- Rail is deliberately NOT filled here: routing Overpass rail corridors
  for ~750 km hauls needs the osmnx/offline builder (follow-up patch);
  the column and dripper precedence are mode-agnostic, so rail geometry
  lands without further code changes when its builder exists.
- Every network failure degrades to None -> the caller keeps the
  documented straight-line fallback. Presentation, never correctness.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models import NetworkEdge
from nexafreight.models.location import Location
from nexafreight.models.network import NetworkNode

logger = logging.getLogger(__name__)

_ORS_URL = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"
# Public-API rate limit is documented at 40 req/min — 1.5 s between calls
# stays comfortably inside it (free daily quota is ~8,000/day per ORS docs).
_POLITE_SLEEP_S = 1.5
_HGV = "driving-hgv"
_CAR = "driving-car"


def parse_ors_geojson(payload: dict[str, Any]) -> str:
    """Extract a compact LineString from an ORS /geojson response.

    Raises ValueError on any shape problem; callers degrade to fallback.
    """
    features = payload.get("features") or []
    if not features:
        raise ValueError("ORS response has no features")
    geom = features[0].get("geometry") or {}
    if geom.get("type") != "LineString":
        raise ValueError(f"unexpected geometry type {geom.get('type')!r}")
    coords = [
        [round(float(lon), 5), round(float(lat), 5)]
        for lon, lat in geom.get("coordinates") or []
    ]
    if len(coords) < 2:
        raise ValueError("ORS geometry has fewer than 2 points")
    import json

    return json.dumps({"type": "LineString", "coordinates": coords})


async def ors_road_route(
    client: httpx.AsyncClient,
    api_key: str,
    o_coord: tuple[float, float],
    d_coord: tuple[float, float],
    profile: str = "driving-hgv",
) -> str | None:
    """ORS directions with a profile fallback; LineString JSON or None.

    (lat, lon) tuples in, GeoJSON (lon, lat) out — same convention as
    the sea adapter. Never raises.

    Day-14b: OSM hgv tagging is sparse outside Europe, so `driving-hgv`
    can be unroutable on long intercity hauls even though ordinary
    driving works. When the requested profile fails, retry ONCE with
    `driving-car` (full OSM road graph). A 429 (rate limit) is retried
    once after a short backoff on the SAME profile — switching profile
    cannot help there.
    """
    geo = await _ors_attempt(client, api_key, o_coord, d_coord, profile)
    if geo is not None:
        return geo
    if profile == _HGV:
        logger.warning("ORS %s unroutable/failed — retrying with %s", _HGV, _CAR)
        geo = await _ors_attempt(client, api_key, o_coord, d_coord, _CAR)
        if geo is not None:
            logger.info("ORS %s fallback succeeded for %s", _CAR, o_coord)
        return geo
    return None


async def _ors_attempt(
    client: httpx.AsyncClient,
    api_key: str,
    o_coord: tuple[float, float],
    d_coord: tuple[float, float],
    profile: str,
) -> str | None:
    """One ORS directions call (one 429 backoff retry inside)."""
    for attempt in (1, 2):
        try:
            resp = await client.post(
                _ORS_URL.format(profile=profile),
                headers={"Authorization": api_key},
                json={
                    "coordinates": [
                        [o_coord[1], o_coord[0]],
                        [d_coord[1], d_coord[0]],
                    ],
                    "radiuses": [10000, 10000]
                },
                timeout=12.0,
            )
            if resp.status_code == 429 and attempt == 1:
                await asyncio.sleep(2.0)  # rate window — same profile helps
                continue
            if resp.status_code != 200:
                logger.warning(
                    "ORS %s %s -> HTTP %d (key/quota/coverage?)",
                    profile, o_coord, resp.status_code,
                )
                return None
            payload = resp.json()
            features = payload.get("features") or []
            if features:
                geom = features[0].get("geometry") or {}
                coords = geom.get("coordinates") or []
                if geom.get("type") == "LineString" and len(coords) == 1:
                    coords.append(coords[0])
            return parse_ors_geojson(payload)
        except ValueError as exc:
            logger.warning("ORS response unusable: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 — presentation path, never raise
            logger.warning("ORS call failed (%s: %s)", type(exc).__name__, exc)
        return None


async def fill_road_edge_geometries(session: AsyncSession) -> dict[str, Any]:
    """Fill geometry_json for ROAD edges that lack it. Never raises.

    Returns stats: {filled, skipped_existing, failed, no_key}.
    """
    settings_key = None
    try:  # settings may be unavailable in stripped test envs — degrade
        from nexafreight.config import get_settings

        s = get_settings()
        settings_key = s.ors_api_key.get_secret_value() if s.ors_api_key else None
    except Exception:  # noqa: BLE001
        settings_key = None
    if not settings_key:
        logger.warning("No ORS API key configured (ors_api_key) — skipping fill")
        return {"filled": 0, "skipped_existing": 0, "failed": 0, "no_key": True}

    node_rows = (await session.execute(select(NetworkNode))).scalars().all()
    node_xy = {n.id: (n.latitude, n.longitude) for n in node_rows}
    loc_rows = (await session.execute(select(Location))).scalars().all()
    loc_xy = {loc.id: (loc.latitude, loc.longitude) for loc in loc_rows}
    edges = (
        await session.execute(
            select(NetworkEdge).where(
                NetworkEdge.mode == "ROAD",
                NetworkEdge.geometry_json.is_(None),
            )
        )
    ).scalars().all()

    filled = failed = 0
    async with httpx.AsyncClient() as client:
        for edge in edges:
            o = node_xy.get(edge.from_node_id) or loc_xy.get(edge.from_node_id)
            d = node_xy.get(edge.to_node_id) or loc_xy.get(edge.to_node_id)
            if o is None or d is None:
                logger.warning("edge %s endpoints unresolved — skipping", edge.id)
                failed += 1
                continue
            geo = await ors_road_route(client, settings_key, o, d)
            if geo:
                edge.geometry_json = geo
                filled += 1
            else:
                failed += 1
            await asyncio.sleep(_POLITE_SLEEP_S)
    await session.commit()
    return {"filled": filled, "skipped_existing": 0, "failed": failed, "no_key": False}
