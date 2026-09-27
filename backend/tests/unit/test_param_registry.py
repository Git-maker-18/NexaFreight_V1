"""Task 22 (E18): every edge param key lives in FALLBACK_DEFAULTS.

The planner and the demo-world builder carry NO inline shadow defaults
anymore; these registry entries are the single source of truth for the
last-resort fallback (fires only when parameter_empirical lacks the key).
Values mirror the former inline shadows exactly -- behaviour-identical.
"""

from __future__ import annotations

from nexafreight.core.params import FALLBACK_DEFAULTS, get_float

# The exact key set carried by network_edges (seeded world) + their former
# inline shadow values.
EDGE_SPEED_KEYS = {
    "sea.feeder.speed_kn": 50.0,
    "sea.panamax.speed_kn": 50.0,
    "rail.dfc.speed_kmh": 50.0,
    "rail.conventional.speed_kmh": 50.0,
    "road.speed_kmh": 50.0,
}
EDGE_COST_KEYS = {
    "sea.cost_usd_per_nm": 0.065,
    "rail.cost_usd_per_km": 0.065,
    "air.cost_usd_per_km": 0.065,
    "road.cost_usd_per_km": 0.065,
}
EDGE_CO2_KEYS = {
    "co2.sea_g_per_tonne_km": 62.0,
    "co2.rail_g_per_tonne_km": 62.0,
    "co2.air_g_per_tonne_km": 62.0,
    "co2.road_g_per_tonne_km": 62.0,
    "co2.road_g_with_toll": 62.0,
}


def test_every_edge_param_key_is_registered() -> None:
    for key, value in {**EDGE_SPEED_KEYS, **EDGE_COST_KEYS, **EDGE_CO2_KEYS}.items():
        assert key in FALLBACK_DEFAULTS, f"E18 regression: {key} not registered"
        assert float(FALLBACK_DEFAULTS[key]) == value


def test_registry_fallback_serves_shadow_values_without_params() -> None:
    """With no parameter rows loaded, get_float returns the registry value."""
    # Clear the in-memory cache so the fallback path actually runs.
    from nexafreight.core import params as params_mod

    saved = dict(params_mod._PARAM_CACHE)
    try:
        params_mod._PARAM_CACHE.clear()
        assert get_float("road.speed_kmh") == 50.0
        assert get_float("sea.cost_usd_per_nm") == 0.065
        assert get_float("co2.sea_g_per_tonne_km") == 62.0
        # air cruise speed keeps its ORIGINAL (pre-E18) registry value,
        # which always shadowed the planner's inline 50.0 anyway.
        assert get_float("air.cruise_speed_kmh") == 860.0
    finally:
        params_mod._PARAM_CACHE.clear()
        params_mod._PARAM_CACHE.update(saved)


def test_planner_source_has_no_inline_shadow_defaults() -> None:
    """Guard: planner.py calls get_float without inline fallback literals."""
    import inspect

    from nexafreight.services import planner

    src = inspect.getsource(planner)
    assert "get_float(edge.cost_param, 0.065)" not in src
    assert "get_float(edge.co2_param, 62.0)" not in src
    assert "get_float(edge.speed_param, 50.0)" not in src
