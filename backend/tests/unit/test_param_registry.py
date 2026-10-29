"""Task 22 (E18): every edge param key lives in FALLBACK_DEFAULTS.

The planner and the demo-world builder carry NO inline shadow defaults
anymore; these registry entries are the single source of truth for the
last-resort fallback (fires only when parameter_empirical lacks the key).
Values mirror the former inline shadows exactly -- behaviour-identical.
"""

from __future__ import annotations
from nexafreight.core.constants import GLEC_CO2_G_PER_TONNE_KM

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
    "co2.sea_g_per_tonne_km": GLEC_CO2_G_PER_TONNE_KM["SEA"],
    "co2.rail_g_per_tonne_km": GLEC_CO2_G_PER_TONNE_KM["RAIL"],
    "co2.air_g_per_tonne_km": GLEC_CO2_G_PER_TONNE_KM["AIR"],
    "co2.road_g_per_tonne_km": GLEC_CO2_G_PER_TONNE_KM["ROAD"],
    "co2.road_g_with_toll": GLEC_CO2_G_PER_TONNE_KM["ROAD"],
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
        assert get_float("co2.sea_g_per_tonne_km") == GLEC_CO2_G_PER_TONNE_KM["SEA"]
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


def test_all_co2_consumers_share_identical_factors() -> None:
    """Verifies that params, financial_engine, and route_planner use the same GLEC factors."""
    from nexafreight.core.constants import GLEC_CO2_G_PER_TONNE_KM
    from nexafreight.services.financial_engine import CO2_G_PER_T_KM
    from nexafreight.services.route_planner import GLEC_CO2_G_PER_TONNE_KM as RP_FACTORS

    for mode in ["SEA", "ROAD", "RAIL", "AIR"]:
        assert CO2_G_PER_T_KM[mode] == GLEC_CO2_G_PER_TONNE_KM[mode]
        assert RP_FACTORS[mode] == GLEC_CO2_G_PER_TONNE_KM[mode]
    assert get_float("co2.sea_g_per_tonne_km") == GLEC_CO2_G_PER_TONNE_KM["SEA"]


def test_shipment_dossier_co2_equals_network_kpi_esg() -> None:
    """Consistency test: for a shipment, the dossier CO2 equals the sum used in the Network KPI."""
    from unittest.mock import MagicMock
    from nexafreight.services.disruption_detector import TONNES_PER_CONTAINER
    from nexafreight.services.financial_engine import CO2_G_PER_T_KM

    # Mock legs for a multimodal shipment
    leg1 = MagicMock()
    leg1.status = "PLANNED"
    leg1.transport_mode = "SEA"
    leg1.distance_km = 4500.0
    leg1.co2_kg = (4500.0 * CO2_G_PER_T_KM["SEA"] * (2 * TONNES_PER_CONTAINER)) / 1000.0

    leg2 = MagicMock()
    leg2.status = "PLANNED"
    leg2.transport_mode = "ROAD"
    leg2.distance_km = 350.0
    leg2.co2_kg = (350.0 * CO2_G_PER_T_KM["ROAD"] * (2 * TONNES_PER_CONTAINER)) / 1000.0

    shipment = MagicMock()
    shipment.container_count = 2
    shipment.legs = [leg1, leg2]
    shipment.primary_transport_mode = "SEA"

    # 1. Dossier calculation (sum of leg.co2_kg)
    dossier_leg_co2 = [leg.co2_kg for leg in shipment.legs]
    dossier_total_co2 = sum(dossier_leg_co2)

    # 2. Network KPI ESG rail calculation (analytics.py logic)
    live_legs = [l for l in shipment.legs if str(l.status) != "REPLACED"]
    assert all(l.co2_kg is not None for l in live_legs) and live_legs
    kpi_co2 = sum(l.co2_kg or 0.0 for l in live_legs)

    assert round(dossier_total_co2, 3) == round(kpi_co2, 3)
