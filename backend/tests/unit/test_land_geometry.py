"""Day-14: land-edge geometry — ORS parsing, edge-cache precedence."""

from __future__ import annotations

import json

import pytest

from nexafreight.enums import TransportMode
from nexafreight.services.land_geometry import parse_ors_geojson


def _dripper_leg_geometry(mode, o, d, edge_geo=None):
    """Import helper: WorldDripper lives in the dripper script module."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "drip_orders", root / "scripts" / "21_drip_orders.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.WorldDripper._leg_geometry(mode, o, d, edge_geo)


def test_parse_ors_geojson_extracts_compact_linestring() -> None:
    payload = {
        "features": [
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.123456, 28.987654], [77.20, 28.30], [77.5, 28.0]],
                }
            }
        ]
    }
    out = parse_ors_geojson(payload)
    data = json.loads(out)
    assert data["type"] == "LineString"
    assert data["coordinates"][0] == [77.12346, 28.98765]  # rounded to 5dp
    assert len(data["coordinates"]) == 3


def test_parse_ors_geojson_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        parse_ors_geojson({"features": []})
    with pytest.raises(ValueError):
        parse_ors_geojson({"features": [{"geometry": {"type": "Point", "coordinates": [1, 2]}}]})
    with pytest.raises(ValueError):
        parse_ors_geojson({"features": [{"geometry": {"type": "LineString", "coordinates": []}}]})


def test_edge_geometry_wins_over_every_fallback() -> None:
    """Cached edge geometry (scripts/25) must be used verbatim — no
    network calls, no straight-line, regardless of mode."""
    cached = json.dumps(
        {"type": "LineString", "coordinates": [[77.0, 28.0], [78.0, 27.0], [79.0, 26.5]]}
    )
    out = _dripper_leg_geometry(
        TransportMode.ROAD, (28.0, 77.0), (26.5, 79.0), edge_geo=cached
    )
    assert out == cached
    out_sea = _dripper_leg_geometry(
        TransportMode.SEA, (18.9, 72.9), (51.9, 4.5), edge_geo=cached
    )
    assert out_sea == cached


def test_fallback_without_edge_geometry_is_densified_line() -> None:
    """No cached geometry -> the day-12d behaviour is unchanged (for AIR a
    great-circle arc; otherwise the densified straight line)."""
    out = _dripper_leg_geometry(TransportMode.AIR, (28.0, 77.0), (26.5, 79.0), None)
    assert len(json.loads(out)["coordinates"]) >= 20  # arc
    out_road = _dripper_leg_geometry(TransportMode.ROAD, (28.0, 77.0), (26.5, 79.0), None)
    assert len(json.loads(out_road)["coordinates"]) <= 17  # densified straight


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _StubClient:
    """Minimal async client double for ors_road_route."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[str] = []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(url)
        return self._responses.pop(0)


def _ors_payload():
    return {
        "features": [
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.0, 28.0], [78.1, 27.4]],
                }
            }
        ]
    }


def test_hgv_failure_falls_back_to_car_profile() -> None:
    import asyncio

    from nexafreight.services.land_geometry import ors_road_route

    client = _StubClient(
        _Resp(404, {"error": {"code": 2010}}),  # hgv unroutable
        _Resp(200, _ors_payload()),             # car works
    )
    out = asyncio.run(ors_road_route(client, "k", (28.0, 77.0), (27.4, 78.1)))
    assert out is not None and "LineString" in out
    assert "driving-hgv" in client.calls[0]
    assert "driving-car" in client.calls[1]


def test_hgv_success_makes_single_call() -> None:
    import asyncio

    from nexafreight.services.land_geometry import ors_road_route

    client = _StubClient(_Resp(200, _ors_payload()))
    out = asyncio.run(ors_road_route(client, "k", (28.0, 77.0), (27.4, 78.1)))
    assert out is not None and len(client.calls) == 1


def test_bad_shape_body_also_triggers_car_fallback() -> None:
    import asyncio

    from nexafreight.services.land_geometry import ors_road_route

    client = _StubClient(_Resp(200, {"features": []}), _Resp(200, _ors_payload()))
    out = asyncio.run(ors_road_route(client, "k", (28.0, 77.0), (27.4, 78.1)))
    assert out is not None and len(client.calls) == 2


def test_double_failure_returns_none() -> None:
    import asyncio

    from nexafreight.services.land_geometry import ors_road_route

    client = _StubClient(_Resp(404), _Resp(404))
    out = asyncio.run(ors_road_route(client, "k", (28.0, 77.0), (27.4, 78.1)))
    assert out is None and len(client.calls) == 2
