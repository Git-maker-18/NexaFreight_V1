import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import text
from nexafreight.services.planner import MultimodalPlanner, GraphCache
from nexafreight.enums import ShipmentPriority
from nexafreight.core import params

@pytest.mark.asyncio
async def test_cache_hit_identical(db_session, graph_cache):
    # Seed corridors puts test nodes and edges into the db. Wait, let's just use what's there
    # Wait, in the test env, we just need basic test network. We can seed it.
    await db_session.execute(text("INSERT INTO locations (locode, name, country_code, location_type, latitude, longitude, created_at, updated_at) VALUES ('INTEST1', 'Test 1', 'IN', 'PORT', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), ('INTEST2', 'Test 2', 'IN', 'PORT', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_nodes (id, locode, name, node_type, modes_json, country_code, latitude, longitude, created_at, updated_at) VALUES (1, 'INTEST1', 'Test 1', 'PORT', '[\"ROAD\"]', 'IN', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), (2, 'INTEST2', 'Test 2', 'PORT', '[\"ROAD\"]', 'IN', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_edges (from_node_id, to_node_id, mode, is_dfc, distance_km, transit_speed_param_key, base_cost_param_key, co2_intensity_param_key, reliability, created_at, updated_at) VALUES (1, 2, 'ROAD', 0, 100.0, 'road.speed_kmh', 'road.cost_usd_per_km', 'co2.road_g_per_tonne_km', 0.95, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.commit()

    planner = MultimodalPlanner(cache=graph_cache)
    
    # Run first time
    res1 = await planner.plan(
        session=db_session,
        shipment_id="ship-1",
        origin_locode="INTEST1",
        dest_locode="INTEST2",
        seed=42,
        persist=False,
    )
    
    assert len(res1) > 0
    assert graph_cache.last_loaded is not None

    # Run second time, should hit cache (no db call, identical output)
    res2 = await planner.plan(
        session=db_session,
        shipment_id="ship-1",
        origin_locode="INTEST1",
        dest_locode="INTEST2",
        seed=42,
        persist=False,
    )
    
    assert len(res2) == len(res1)
    assert res1[0].total_cost_usd == res2[0].total_cost_usd

@pytest.mark.asyncio
async def test_cache_invalidation_and_refresh(db_session, graph_cache):
    await db_session.execute(text("INSERT INTO locations (locode, name, country_code, location_type, latitude, longitude, created_at, updated_at) VALUES ('INTEST3', 'Test 3', 'IN', 'PORT', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), ('INTEST4', 'Test 4', 'IN', 'PORT', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_nodes (id, locode, name, node_type, modes_json, country_code, latitude, longitude, created_at, updated_at) VALUES (3, 'INTEST3', 'Test 3', 'PORT', '[\"ROAD\"]', 'IN', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), (4, 'INTEST4', 'Test 4', 'PORT', '[\"ROAD\"]', 'IN', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_edges (from_node_id, to_node_id, mode, is_dfc, distance_km, transit_speed_param_key, base_cost_param_key, co2_intensity_param_key, reliability, created_at, updated_at) VALUES (3, 4, 'ROAD', 0, 100.0, 'road.speed_kmh', 'road.cost_usd_per_km', 'co2.road_g_per_tonne_km', 0.95, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO parameter_empirical (key, value, source, as_of, derivation_method) VALUES ('road_speed', 50.0, 'test', CURRENT_TIMESTAMP, 'test'), ('road_cost', 1.0, 'test', CURRENT_TIMESTAMP, 'test'), ('road_co2', 1.0, 'test', CURRENT_TIMESTAMP, 'test') ON CONFLICT(key) DO UPDATE SET value=excluded.value"))
    await db_session.commit()
    await params.refresh_parameters(db_session)

    planner = MultimodalPlanner(cache=graph_cache)
    res1 = await planner.plan(
        session=db_session,
        shipment_id="ship-2",
        origin_locode="INTEST3",
        dest_locode="INTEST4",
        seed=42,
        persist=False,
    )
    
    cost1 = res1[0].total_cost_usd

    # Mutate edge distance
    await db_session.execute(text("UPDATE network_edges SET distance_km = 200.0 WHERE from_node_id = 3 AND to_node_id = 4"))
    await db_session.commit()

    # Plan again immediately - should still use cached value (cost should be same)
    res2 = await planner.plan(
        session=db_session,
        shipment_id="ship-2",
        origin_locode="INTEST3",
        dest_locode="INTEST4",
        seed=42,
        persist=False,
    )
    assert res2[0].total_cost_usd == cost1

    # Invalidate cache by changing last_loaded
    graph_cache.last_loaded = datetime.now(UTC) - timedelta(minutes=20)
    
    # Plan again - should refresh and compute new cost
    res3 = await planner.plan(
        session=db_session,
        shipment_id="ship-2",
        origin_locode="INTEST3",
        dest_locode="INTEST4",
        seed=42,
        persist=False,
    )
    assert res3[0].total_cost_usd > cost1

@pytest.mark.asyncio
async def test_cache_isolation(db_session, graph_cache):
    cache2 = GraphCache()
    assert graph_cache is not cache2

    await db_session.execute(text("INSERT INTO locations (locode, name, country_code, location_type, latitude, longitude, created_at, updated_at) VALUES ('INTEST5', 'Test 5', 'IN', 'PORT', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), ('INTEST6', 'Test 6', 'IN', 'PORT', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_nodes (id, locode, name, node_type, modes_json, country_code, latitude, longitude, created_at, updated_at) VALUES (5, 'INTEST5', 'Test 5', 'PORT', '[\"ROAD\"]', 'IN', 10.0, 20.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), (6, 'INTEST6', 'Test 6', 'PORT', '[\"ROAD\"]', 'IN', 11.0, 21.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.execute(text("INSERT INTO network_edges (from_node_id, to_node_id, mode, is_dfc, distance_km, transit_speed_param_key, base_cost_param_key, co2_intensity_param_key, reliability, created_at, updated_at) VALUES (5, 6, 'ROAD', 0, 100.0, 'road.speed_kmh', 'road.cost_usd_per_km', 'co2.road_g_per_tonne_km', 0.95, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    await db_session.commit()

    planner1 = MultimodalPlanner(cache=graph_cache)
    await planner1.plan(
        session=db_session,
        shipment_id="ship-3",
        origin_locode="INTEST5",
        dest_locode="INTEST6",
        persist=False,
    )
    
    assert graph_cache.last_loaded is not None
    assert cache2.last_loaded is None
