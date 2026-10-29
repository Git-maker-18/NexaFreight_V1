#!/usr/bin/env python3
r"""chartroom_5d upgrade: dress_legs_for_reality -> rev2 (real engines + ORS throttle + KEPT_REAL).

Self-verifying whole-function replacement. Works from ANY prior version of the
function (bent-polyline original, hotfix2 rev1, or already-rev2 = no-op).
Run from backend:  python upgrade_routing_pass.py
"""
import py_compile
from pathlib import Path

TARGET = Path("scripts") / "20_build_demo_world.py"
START = "async def dress_legs_for_reality() -> dict:"
END_MARK = "\nasync def main()"

NEW_FUNC = 'async def dress_legs_for_reality() -> dict:\n    """Fill legs with REAL routing-engine geometry + clock-true statuses (wave 5D/5E).\n\n    Every leg gets geometry from the production routing adapters — the same\n    engines the planner and reroute APIs use:\n      SEA  → searoute (real maritime lanes: Suez / Malacca / Panama)\n      AIR  → great-circle arcs (geodesic interpolation)\n      ROAD/RAIL → OpenRouteService when ORS_API_KEY is set, otherwise the\n                   adapter\'s great-circle APPROXIMATE fallback.\n    If an engine raises, the leg falls back to a mode-flavoured bend and is\n    counted as FALLBACK_BEND in the log so nothing is silently fake.\n\n    Also grades leg status against wall-clock (COMPLETED / IN_PROGRESS /\n    PLANNED) and derives shipment status from its legs. Idempotent.\n    """\n    import json as _json\n    import math as _math\n\n    from nexafreight.adapters.routing import (\n        RoadRouter,\n        compute_air_route,\n        compute_sea_route,\n    )\n    from nexafreight.models.leg import Leg\n    from nexafreight.models.location import Location\n    from nexafreight.models.shipment import Shipment\n\n    def _bend(a: tuple[float, float], b: tuple[float, float], frac: float, off: float) -> list[float]:\n        lat = a[1] + (b[1] - a[1]) * frac\n        lon = a[0] + (b[0] - a[0]) * frac\n        d = _math.hypot(b[0] - a[0], b[1] - a[1])\n        if d == 0:\n            return [round(lon, 4), round(lat, 4)]\n        nx, ny = -(b[1] - a[1]) / d, (b[0] - a[0]) / d\n        return [round(lon + nx * off * d, 4), round(lat + ny * off * d, 4)]\n\n    settings = get_settings()\n    ors_key = None\n    if getattr(settings, "ors_api_key", None):\n        ors_key = settings.ors_api_key.get_secret_value()\n    road_router = RoadRouter(api_key=ors_key)\n\n    import time as _time\n\n    now = datetime.now(UTC).replace(tzinfo=None)\n    sources: dict[str, int] = {}\n    async with get_session_factory()() as session:\n        locs = {\n            row.id: (float(row.longitude), float(row.latitude))\n            for row in (await session.execute(select(Location))).scalars()\n        }\n        legs = (await session.execute(select(Leg))).scalars().all()\n\n        filled = 0\n        by_shipment: dict[str, list[tuple[datetime, datetime]]] = {}\n        for leg in legs:\n            a = locs.get(leg.origin_id)\n            b = locs.get(leg.destination_id)\n            if a and b:\n                mode = str(leg.transport_mode).split(".")[-1]\n                prov = str(getattr(leg, "provenance", "") or "").split(".")[-1].upper()\n                if prov == "REAL" and leg.route_geometry_json:\n                    # Already engine-routed in a previous pass — keep the real\n                    # geometry, don\'t burn API quota re-routing it.\n                    sources["KEPT_REAL"] = sources.get("KEPT_REAL", 0) + 1\n                    filled += 1\n                else:\n                    source = "FALLBACK_BEND"\n                    geom_str: str | None = None\n                    try:\n                        if mode == "SEA":\n                            res = compute_sea_route(a[1], a[0], b[1], b[0])\n                            geom_str = res.geometry_geojson\n                            source = "SEAROUTE"\n                        elif mode == "AIR":\n                            res = compute_air_route(a[1], a[0], b[1], b[0])\n                            geom_str = res.geometry_geojson\n                            source = "GREAT_CIRCLE"\n                        else:\n                            res = road_router.compute((a[1], a[0]), (b[1], b[0]))\n                            geom_str = res.geometry_geojson\n                            source = "ORS" if res.source == "OPENROUTESERVICE" else "ROAD_FALLBACK"\n                    except Exception as exc:  # noqa: BLE001\n                        log.warning("Real routing failed for leg %s (%s): %s — using bend fallback", leg.id, mode, exc)\n                    if geom_str is None or "LineString" not in geom_str:\n                        coords = [list(a)]\n                        if mode == "SEA":\n                            coords += [_bend(a, b, 0.35, 0.18), _bend(a, b, 0.65, 0.22)]\n                        elif mode == "AIR":\n                            coords += [_bend(a, b, 0.5, 0.10)]\n                        else:\n                            coords += [_bend(a, b, 0.3, 0.06), _bend(a, b, 0.7, -0.05)]\n                        coords.append(list(b))\n                        geom_str = _json.dumps({"type": "LineString", "coordinates": coords})\n                        source = "FALLBACK_BEND"\n                    leg.route_geometry_json = geom_str\n                    leg.provenance = "DERIVED"\n                    sources[source] = sources.get(source, 0) + 1\n                    filled += 1\n                    if ors_key and mode not in ("SEA", "AIR"):\n                        _time.sleep(1.5)  # ORS free tier: stay under 40 req/min\n\n            dep = leg.planned_departure.replace(tzinfo=None) if leg.planned_departure.tzinfo else leg.planned_departure\n            arr = leg.planned_arrival.replace(tzinfo=None) if leg.planned_arrival.tzinfo else leg.planned_arrival\n            if dep <= now < arr:\n                leg.status = "IN_PROGRESS"\n            elif arr <= now:\n                leg.status = "COMPLETED"\n            else:\n                leg.status = "PLANNED"\n            by_shipment.setdefault(str(leg.shipment_id), []).append((dep, arr))\n\n        shipments = (await session.execute(select(Shipment))).scalars().all()\n        counts: dict[str, int] = {"IN_TRANSIT": 0, "PLANNED": 0, "DELIVERED": 0}\n        for sh in shipments:\n            windows = by_shipment.get(str(sh.id), [])\n            if any(dep <= now < arr for dep, arr in windows):\n                sh.status = "IN_TRANSIT"\n            elif windows and all(arr <= now for _, arr in windows):\n                sh.status = "DELIVERED"\n            else:\n                sh.status = "PLANNED"\n            counts[str(sh.status).split(".")[-1]] = counts.get(str(sh.status).split(".")[-1], 0) + 1\n\n        await session.commit()\n\n    log.info(\n        "Legs dressed for reality: %d geometries from %s; shipments %s",\n        filled,\n        sources or "{}",\n        counts,\n    )\n    return {"geometries": filled, "sources": sources, "shipments": counts}\n\n'


def main() -> int:
    if not TARGET.exists():
        print("FAIL: scripts/20_build_demo_world.py not found - run from backend dir")
        return 1
    src = TARGET.read_text(encoding="utf-8")
    if START not in src:
        print("FAIL: dress_legs_for_reality() not found - unexpected file")
        return 1
    s = src.index(START)
    e = src.index(END_MARK, s)
    if "KEPT_REAL" in src[s:e] and "_time.sleep(1.5)" in src[s:e]:
        print("OK: already rev2 (KEPT_REAL + ORS throttle present) - nothing to do")
        return 0
    out = src[:s] + NEW_FUNC + src[e:]
    TARGET.write_text(out, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    chk = TARGET.read_text(encoding="utf-8")
    ok = ("KEPT_REAL" in chk) and ("_time.sleep(1.5)" in chk) and ("compute_sea_route" in chk)
    print("UPGRADED + compiled OK" if ok else "FAIL: post-check")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
