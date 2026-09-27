"""Regression test for E23: planner heap tie-crash (found by the demo world).

_dijkstra pushed (obj, node, arrival_ts, path) onto a heapq; on an exact tie
(routine under deterministic schedules — e.g. two identical parallel services)
Python falls through to comparing the LegKPI path, which has no ordering:
TypeError: '<' not supported between instances of 'LegKPI' and 'LegKPI'.
The same pattern existed in the Yen k-shortest candidates heap.

This test builds a two-node network with two IDENTICAL services leaving at
the same instant and demands an itinerary — it crashed before the fix,
returns ranked plans now.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models.network import EdgeSchedule, NetworkEdge, NetworkNode
from nexafreight.services.planner import MultimodalPlanner

Q_TIME = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def tie_network(db_session: AsyncSession):
    """Two nodes joined by two IDENTICAL same-time services — forces exact ties."""
    a = NetworkNode(
        locode="TIEA",
        name="Tie Origin",
        node_type="ROAD_HUB",
        latitude=26.0,
        longitude=80.0,
        country_code="IN",
        modes_json='["ROAD"]',
    )
    b = NetworkNode(
        locode="TIEB",
        name="Tie Destination",
        node_type="ROAD_HUB",
        latitude=25.0,
        longitude=81.0,
        country_code="IN",
        modes_json='["ROAD"]',
    )
    db_session.add_all([a, b])
    await db_session.flush()

    for i in range(2):  # identical parallel edges with identical schedules
        edge = NetworkEdge(
            from_node_id=a.id,
            to_node_id=b.id,
            mode="ROAD",
            distance_km=120.0,
            transit_speed_param_key="road.speed.default",  # resolves via FALLBACK_DEFAULTS
            base_cost_param_key="road.cost_usd_per_tkm",
            co2_intensity_param_key="co2.road_g_per_tonne_km",
            reliability=0.95,
            is_dfc=False,
        )
        db_session.add(edge)
        await db_session.flush()
        dep = Q_TIME + timedelta(hours=1)
        db_session.add(
            EdgeSchedule(
                edge_id=edge.id,
                service_name=f"TIE-SVC-{i}",
                departure_at=dep,
                arrival_at=dep + timedelta(hours=3),  # 120 km @ 40 km/h ≈ 3 h
                provenance="SIMULATED",
            )
        )
    await db_session.commit()
    return a, b


@pytest.mark.asyncio
async def test_identical_parallel_services_do_not_crash_heap(db_session: AsyncSession, tie_network):
    _a, _b = tie_network
    planner = MultimodalPlanner()

    itineraries = await planner.plan(
        db_session,
        shipment_id="tie-test-0001",
        origin_locode="TIEA",
        dest_locode="TIEB",
        query_time=Q_TIME,
        persist=False,
    )
    assert itineraries, "planner must return at least one itinerary on a tied network"
    assert all(i.total_time_h > 0 for i in itineraries)
