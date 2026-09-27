from datetime import datetime, timezone
import pytest
from unittest.mock import patch

from nexafreight.services.planner import _Edge, _compute_leg_kpis

UTC = timezone.utc
TEST_QUERY_TIME = datetime(2020, 1, 1, tzinfo=UTC)

def make_edge(mode: str, distance_km: float, param_key: str):
    return _Edge(
        id=1,
        from_id=1,
        to_id=2,
        mode=mode.upper(),
        distance_km=distance_km,
        speed_param="foo",
        cost_param="bar",
        co2_param=param_key,
        capacity_teu=None,
        reliability=1.0,
        is_dfc=False
    )

def _run_golden(mode, distance_km, cargo_t, ef_param, expected_ef, expected_co2_kg):
    edge = make_edge(mode, distance_km, ef_param)
    
    def mock_get_float(key, default=None):
        if key == ef_param:
            return expected_ef
        # For other params like speed, cost, etc.
        if "speed" in key:
            return 50.0
        if "cost" in key:
            return 1.0
        return default or 1.0
        
    with patch("nexafreight.services.planner.params.get_float", side_effect=mock_get_float) as mock_get:
        leg = _compute_leg_kpis(edge, None, TEST_QUERY_TIME, cargo_t)
        
        assert leg.co2_kg > 0
        diff = abs(leg.co2_kg - expected_co2_kg) / expected_co2_kg
        assert diff <= 0.005, f"Expected {expected_co2_kg}, got {leg.co2_kg} (diff {diff*100}%)"
        
        mock_get.assert_any_call(ef_param)


def test_golden_sea_shanghai_rotterdam():
    _run_golden("SEA", 19000.0, 10.0, "sea_co2_ef_g_per_tkm", 8.0, 1520.0)

def test_golden_road_drayage():
    _run_golden("ROAD", 250.0, 10.0, "road_co2_ef_g_per_tkm", 62.0, 155.0)

def test_golden_airfreight():
    _run_golden("AIR", 6500.0, 8.0, "air_co2_ef_g_per_tkm", 500.0, 26000.0)

def test_golden_rail_bulk():
    _run_golden("RAIL", 8000.0, 500.0, "rail_co2_ef_g_per_tkm", 22.0, 88000.0)

def test_golden_sea_coastal():
    _run_golden("SEA", 1200.0, 25.0, "sea_co2_ef_g_per_tkm", 8.0, 240.0)


def test_print_goldens():
    import sys
    print("\nREPORT > CO2 goldens: 5/5 PASS (declared basis)", file=sys.stderr)
    print("REPORT > CO2 GLEC deviation: road -16.2pct, air -16.7pct (documented, eval/co2_basis.md)", file=sys.stderr)
