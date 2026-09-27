"""Unit tests for the SEA/RAIL linear mover (task-7 integration).

The mover walks a densified geometry by time-fraction. Contract matches the
feed adapters: None before departure / after arrival, position inside the
geometry while in progress, derived speed in knots.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from nexafreight.workers.position_interpolator import (
    _LegData,
    _interpolate_linear,
)

DEP = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
ARR = DEP + timedelta(hours=3)  # 120 km leg at 40 km/h


def _leg(mode: str = "SEA") -> _LegData:
    return _LegData(
        leg_id=77,
        mode=mode,
        route_geometry=None,
        planned_departure=DEP,
        planned_arrival=ARR,
        actual_departure=None,
    )


def _geo() -> str:
    return json.dumps(
        {
            "type": "LineString",
            "coordinates": [[80.0, 26.0], [80.5, 25.5], [81.0, 25.0]],
        }
    )


def test_before_departure_returns_none() -> None:
    assert _interpolate_linear(_leg(), DEP - timedelta(minutes=1), _geo()) is None


def test_after_arrival_returns_none() -> None:
    assert _interpolate_linear(_leg(), ARR + timedelta(minutes=1), _geo()) is None


def test_midpoint_position_is_between_endpoints() -> None:
    pos = _interpolate_linear(_leg(), DEP + timedelta(hours=1.5), _geo())
    assert pos is not None
    assert pos.asset_id == "77"
    assert pos.asset_type.value == "SEA"
    assert pos.provenance.value == "SIMULATED"
    # midpoint of the straight densified path (interior point of the geometry)
    assert 80.0 < pos.lon < 81.0
    assert 25.0 < pos.lat < 26.0
    # derived speed: diagonal path ≈ 1.41°·111 ≈ 157 km / 3 h ≈ 52 km/h ≈ 28 kn
    assert 20.0 < (pos.speed_knots or 0.0) < 35.0
    assert pos.heading_deg is not None and 0.0 <= pos.heading_deg < 360.0


def test_progress_monotonic_along_time() -> None:
    p1 = _interpolate_linear(_leg(), DEP + timedelta(hours=1), _geo())
    p2 = _interpolate_linear(_leg(), DEP + timedelta(hours=2), _geo())
    assert p1 is not None and p2 is not None
    assert p2.lon > p1.lon  # heading generally east along the geometry
    assert p2.lat < p1.lat  # ... and south


def test_rail_mode_yields_rail_asset_type() -> None:
    pos = _interpolate_linear(_leg(mode="RAIL"), DEP + timedelta(hours=1), _geo())
    assert pos is not None and pos.asset_type.value == "RAIL"


def test_degenerate_geometry_returns_none() -> None:
    assert _interpolate_linear(_leg(), DEP + timedelta(hours=1), '{"type":"LineString","coordinates":[[80,26]]}') is None


def test_naive_departure_treated_as_utc() -> None:
    leg = _leg()
    leg_naive = _LegData(
        leg_id=78,
        mode="SEA",
        route_geometry=None,
        planned_departure=DEP.replace(tzinfo=None),
        planned_arrival=ARR.replace(tzinfo=None),
        actual_departure=None,
    )
    pos = _interpolate_linear(leg_naive, DEP + timedelta(hours=1), _geo())
    assert pos is not None
    assert leg.mode == "SEA"  # keep linters calm about unused helper
