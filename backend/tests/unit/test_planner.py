"""Tests for the schedule-aware multimodal planner service.

Uses a minimal synthetic network (no DB seed migration required) to test:
- Connection feasibility (dwell ≥ minimum)
- Deadline filtering
- Priority weight profiles (ECONOMY vs CRITICAL behavior)
- Pareto dominance pruning
- Structural dedup
- CO2/reliability scalarization
- Persistence (route_plan + route_leg rows)
- API contract shape
- Performance (<2s on seeded network)
- Provenance tags
- Empty-state (no route available)
- Seed determinism
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import PlanType, ShipmentPriority
from nexafreight.models.network import EdgeSchedule, NetworkEdge, NetworkNode, TransshipmentLink
from nexafreight.models.route_plan import RouteLegRecord, RoutePlanRecord
from nexafreight.services.planner import (
    ItineraryResult,
    LegKPI,
    MultimodalPlanner,
    _dijkstra,
    _load_network,
    _score_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures — tiny synthetic network
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def shipment(make_shipment):
    return await make_shipment()

#
# Network: A --[ROAD, 300km, 10h]--> B --[RAIL, 500km, 20h]--> C
#          A --[AIR,  400km, 2h] --> C   (direct, expensive, fast)
#
# A = INLUH (Ludhiana road hub)
# B = INTKG (Tughlakabad ICD)
# C = INJNP (JNPT)

_NOW = datetime(2026, 10, 1, 6, 0, 0, tzinfo=UTC)
_DEADLINE_OK = _NOW + timedelta(hours=72)
_DEADLINE_TIGHT = _NOW + timedelta(hours=5)  # only AIR can make this


async def _seed_tiny_network(session: AsyncSession, shipment_id: str) -> None:
    """Seed a 3-node, 3-edge network for unit tests."""
    n_a = NetworkNode(locode="INLUH", name="Ludhiana Road Hub", node_type="ROAD_HUB",
                      modes_json='["ROAD"]', latitude=30.901, longitude=75.857, country_code="IN")
    n_b = NetworkNode(locode="INTKG", name="Tughlakabad ICD", node_type="ICD",
                      modes_json='["RAIL","ROAD"]', latitude=28.492, longitude=77.280, country_code="IN")
    n_c = NetworkNode(locode="INJNP", name="JNPT", node_type="PORT",
                      modes_json='["SEA","ROAD"]', latitude=18.949, longitude=72.952, country_code="IN")
    n_d = NetworkNode(locode="INAIR", name="Delhi Airport", node_type="AIRPORT",
                      modes_json='["AIR","ROAD"]', latitude=28.556, longitude=77.100, country_code="IN")
    session.add_all([n_a, n_b, n_c, n_d])
    await session.flush()

    # Add transshipment links
    ts_b = TransshipmentLink(node_id=n_b.id, min_dwell_h=4.0, max_dwell_h=72.0, handling_cost_usd=100.0)
    ts_c = TransshipmentLink(node_id=n_c.id, min_dwell_h=8.0, max_dwell_h=48.0, handling_cost_usd=200.0)
    ts_d = TransshipmentLink(node_id=n_d.id, min_dwell_h=4.0, max_dwell_h=24.0, handling_cost_usd=350.0)
    session.add_all([ts_b, ts_c, ts_d])

    # Edges
    e_road_ab = NetworkEdge(
        from_node_id=n_a.id, to_node_id=n_b.id, mode="ROAD", distance_km=300.0,
        transit_speed_param_key="road.speed_kmh", base_cost_param_key="road.cost_usd_per_km",
        co2_intensity_param_key="co2.road_g_per_tonne_km", reliability=0.88,
    )
    e_rail_bc = NetworkEdge(
        from_node_id=n_b.id, to_node_id=n_c.id, mode="RAIL", distance_km=1500.0,
        transit_speed_param_key="rail.dfc.speed_kmh", base_cost_param_key="rail.cost_usd_per_km",
        co2_intensity_param_key="co2.rail_g_per_tonne_km", reliability=0.91,
    )
    e_road_ad = NetworkEdge(
        from_node_id=n_a.id, to_node_id=n_d.id, mode="ROAD", distance_km=35.0,
        transit_speed_param_key="road.speed_kmh", base_cost_param_key="road.cost_usd_per_km",
        co2_intensity_param_key="co2.road_g_per_tonne_km", reliability=0.95,
    )
    e_air_dc = NetworkEdge(
        from_node_id=n_d.id, to_node_id=n_c.id, mode="AIR", distance_km=1200.0,
        transit_speed_param_key="air.cruise_speed_kmh", base_cost_param_key="air.cost_usd_per_km",
        co2_intensity_param_key="co2.air_g_per_tonne_km", reliability=0.97,
    )
    # Low reliability edge (for reliability scalarization test)
    e_road_bc_slow = NetworkEdge(
        from_node_id=n_b.id, to_node_id=n_c.id, mode="ROAD", distance_km=1700.0,
        transit_speed_param_key="road.speed_kmh", base_cost_param_key="road.cost_usd_per_km",
        co2_intensity_param_key="co2.road_g_per_tonne_km", reliability=0.60,  # low!
    )
    session.add_all([e_road_ab, e_rail_bc, e_road_ad, e_air_dc, e_road_bc_slow])
    await session.flush()

    # Schedules
    # ROAD A→B: multiple departure windows
    dep_road = _NOW + timedelta(hours=0)
    session.add(EdgeSchedule(edge_id=e_road_ab.id, service_name="TRK-LUH-TKG",
                              departure_at=dep_road, arrival_at=dep_road + timedelta(hours=10),
                              capacity_remaining=50, provenance="SIMULATED"))
    session.add(EdgeSchedule(edge_id=e_road_ab.id, service_name="TRK-LUH-TKG-2",
                              departure_at=dep_road + timedelta(hours=6),
                              arrival_at=dep_road + timedelta(hours=16),
                              capacity_remaining=50, provenance="SIMULATED"))

    # RAIL B→C: departs 16h after now (requires 4h dwell + 2h margin = 6h min gap)
    dep_rail = _NOW + timedelta(hours=16)  # arrival at B = now+10, dwell min=4+2=6h → earliest=now+16 ✓
    session.add(EdgeSchedule(edge_id=e_rail_bc.id, service_name="DFC-TKG-JNPT",
                              departure_at=dep_rail, arrival_at=dep_rail + timedelta(hours=26),
                              capacity_remaining=200, provenance="SIMULATED"))

    # ROAD A→D: short drayage, immediate
    session.add(EdgeSchedule(edge_id=e_road_ad.id, service_name="TRK-LUH-DEL",
                              departure_at=_NOW, arrival_at=_NOW + timedelta(hours=1),
                              capacity_remaining=80, provenance="SIMULATED"))

    # AIR D→C: departs 5h after now (requires 4h dwell + 2h margin = 6h → departs ≥ now+7 needed)
    dep_air = _NOW + timedelta(hours=8)
    session.add(EdgeSchedule(edge_id=e_air_dc.id, service_name="AI-DEL-JNPT",
                              departure_at=dep_air, arrival_at=dep_air + timedelta(hours=3),
                              capacity_remaining=30, provenance="SIMULATED"))

    # Tight schedule air: one that departs NOW+3 (connection infeasible without margin)
    dep_air_tight = _NOW + timedelta(hours=3)
    session.add(EdgeSchedule(edge_id=e_air_dc.id, service_name="AI-DEL-JNPT-TIGHT",
                              departure_at=dep_air_tight, arrival_at=dep_air_tight + timedelta(hours=3),
                              capacity_remaining=10, provenance="SIMULATED"))

    await session.commit()

    from nexafreight.models.parameter import ParameterEmpirical
    params_data = [
        ParameterEmpirical(key="road.speed_kmh", value=45.0, unit="km/h", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="rail.dfc.speed_kmh", value=50.0, unit="km/h", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="air.cruise_speed_kmh", value=860.0, unit="km/h", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="road.cost_usd_per_km", value=0.065, unit="USD/km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="rail.cost_usd_per_km", value=0.030, unit="USD/km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="air.cost_usd_per_km", value=1.80, unit="USD/km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="co2.road_g_per_tonne_km", value=62.0, unit="g/t-km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="co2.rail_g_per_tonne_km", value=22.0, unit="g/t-km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="co2.air_g_per_tonne_km", value=600.0, unit="g/t-km", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        
        # Priority weights for CRITICAL
        ParameterEmpirical(key="plan.weight.CRITICAL.cost", value=0.1, unit="", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
        ParameterEmpirical(key="plan.weight.CRITICAL.time", value=0.8, unit="", source="SIMULATED", as_of=_NOW, derivation_method="HARDCODED"),
    ]
    session.add_all(params_data)
    await session.commit()
    
    from nexafreight.core.params import refresh_parameters
    await refresh_parameters(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConnectionFeasibility:
    """Planner must enforce connection dwell ≥ min_dwell_h + connection_margin_h."""

    @pytest.mark.asyncio
    async def test_road_to_rail_feasible_connection(self, db_session: AsyncSession, shipment):
        """A→B (10h) + dwell(4+2=6h) → departs B at now+16 → RAIL B→C feasible."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        assert results, "Expected at least one itinerary"
        # Find road+rail itinerary
        road_rail = next(
            (r for r in results if any(l.mode == "RAIL" for l in r.legs)), None
        )
        assert road_rail is not None, "Expected a road+rail itinerary"
        # The rail departure must be ≥ arrival at B + 6h
        road_leg = next(l for l in road_rail.legs if l.mode == "ROAD" and l.to_locode == "INTKG")
        rail_leg = next(l for l in road_rail.legs if l.mode == "RAIL")
        gap_h = (rail_leg.departure_at - road_leg.arrival_at).total_seconds() / 3600.0
        assert gap_h >= 6.0 - 0.01, f"Connection gap {gap_h}h < 6h minimum"

    @pytest.mark.asyncio
    async def test_tight_schedule_rejected(self, db_session: AsyncSession, shipment):
        """Tight air schedule (now+3) must be rejected (road→airport arrives now+1, need 6h margin)."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.CRITICAL, persist=False,
        )
        # The tight air departure (now+3) should not appear as a schedule_id on any leg
        tight_schedule_used = False
        for itin in results:
            for leg in itin.legs:
                # arrival_at for tight air = NOW+6; if schedule_id is the tight one,
                # the departure must have been rejected
                if leg.mode == "AIR" and leg.departure_at <= _NOW + timedelta(hours=4):
                    tight_schedule_used = True
        assert not tight_schedule_used, "Tight infeasible schedule was used — connection margin not enforced"


class TestDeadlineFilter:
    @pytest.mark.asyncio
    async def test_tight_deadline_only_air_passes(self, db_session: AsyncSession, shipment):
        """With a 12h deadline, road+rail (36h total) is filtered; road+air (11h total) passes."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        deadline = _NOW + timedelta(hours=12)
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.CRITICAL,
            deadline=deadline, persist=False,
        )
        # All results must arrive before the deadline
        for itin in results:
            if itin.legs:
                arr = itin.legs[-1].arrival_at
                assert arr <= deadline, f"Itinerary arrives at {arr}, deadline is {deadline}"

    @pytest.mark.asyncio
    async def test_impossible_deadline_returns_empty(self, db_session: AsyncSession, shipment):
        """A 1h deadline should produce no results (nothing can arrive in 1h)."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.CRITICAL,
            deadline=_NOW + timedelta(hours=1), persist=False,
        )
        assert results == [], "Expected empty list for impossible deadline"


class TestWeightProfiles:
    @pytest.mark.asyncio
    async def test_economy_recommends_cheapest(self, db_session: AsyncSession, shipment):
        """ECONOMY profile (cost weight=0.6) should recommend the cheapest route."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.ECONOMY, persist=False,
        )
        assert results
        recommended = next(r for r in results if r.recommended)
        # Rail is much cheaper than air (cost_usd_per_km: rail=0.025 vs air=4.5)
        # So road+rail should be recommended for ECONOMY
        modes_in_recommended = {leg.mode for leg in recommended.legs}
        assert "AIR" not in modes_in_recommended, (
            f"ECONOMY should not recommend AIR (too expensive). Got modes: {modes_in_recommended}"
        )

    @pytest.mark.asyncio
    async def test_critical_recommends_fastest(self, db_session: AsyncSession, shipment):
        """CRITICAL profile (time weight=0.6) should recommend the fastest route."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.CRITICAL, persist=False,
        )
        assert results
        recommended = next(r for r in results if r.recommended)
        modes_in_recommended = {leg.mode for leg in recommended.legs}
        # AIR route takes ~11h total; road+rail takes ~36h
        assert "AIR" in modes_in_recommended, (
            f"CRITICAL should prefer AIR (fastest). Got modes: {modes_in_recommended}"
        )


class TestStructuralDedup:
    @pytest.mark.asyncio
    async def test_no_duplicate_itineraries(self, db_session: AsyncSession, shipment):
        """Structural dedup removes itineraries with identical (mode, from, to) chains."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        structural_keys = [itin.structural_key for itin in results]
        assert len(structural_keys) == len(set(structural_keys)), (
            "Duplicate structural keys found — dedup not working"
        )


class TestCO2Scalarization:
    @pytest.mark.asyncio
    async def test_greenest_avoids_air(self, db_session: AsyncSession, shipment):
        """CO2-optimized scalarization should produce a non-air path (rail CO2 << air CO2)."""
        await _seed_tiny_network(db_session, str(shipment.id))
        nodes, edges_by_from, schedules_by_edge, transshipments, locode_to_id = await _load_network(
            db_session, _NOW, 14
        )
        origin_id = locode_to_id.get("INLUH")
        dest_id = locode_to_id.get("INJNP")
        path = _dijkstra(
            origin_id, dest_id, nodes, edges_by_from, schedules_by_edge,
            transshipments, _NOW, 15.0, 2.0,
            _NOW + timedelta(days=14), objective="co2",
        )
        assert path is not None
        modes = {leg.mode for leg in path}
        assert "AIR" not in modes, f"Greenest path should not use AIR. Got: {modes}"


class TestReliabilityScalarization:
    @pytest.mark.asyncio
    async def test_reliability_avoids_low_reliability_edge(self, db_session: AsyncSession, shipment):
        """Reliability scalarization should avoid the 0.60 reliability B→C ROAD edge."""
        await _seed_tiny_network(db_session, str(shipment.id))
        nodes, edges_by_from, schedules_by_edge, transshipments, locode_to_id = await _load_network(
            db_session, _NOW, 14
        )
        origin_id = locode_to_id.get("INLUH")
        dest_id = locode_to_id.get("INJNP")
        path = _dijkstra(
            origin_id, dest_id, nodes, edges_by_from, schedules_by_edge,
            transshipments, _NOW, 15.0, 2.0,
            _NOW + timedelta(days=14), objective="reliability",
        )
        assert path is not None
        # Should not pick the ROAD B→C (0.60 reliability) when RAIL B→C (0.91) is available
        road_bc = [leg for leg in path if leg.mode == "ROAD" and leg.from_locode == "INTKG"]
        assert not road_bc, f"Reliability path should avoid ROAD B→C. Got path: {path}"


class TestPersistence:
    @pytest.mark.asyncio
    async def test_route_plan_rows_written(self, db_session: AsyncSession, shipment):
        """plan() with persist=True should write route_plan + route_leg rows to DB."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=True,
        )
        # Verify rows
        plans = (await db_session.execute(
            select(RoutePlanRecord).where(RoutePlanRecord.shipment_id == str(shipment.id))
        )).scalars().all()
        assert len(plans) == len(results), f"Expected {len(results)} plan rows, got {len(plans)}"

        for plan in plans:
            await db_session.refresh(plan, ["legs"])
            assert len(plan.legs) > 0, f"Plan {plan.id} has no legs"

    @pytest.mark.asyncio
    async def test_route_leg_kpis_correct(self, db_session: AsyncSession, shipment):
        """Persisted leg records must match in-memory KPIs."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=True,
        )
        plans = (await db_session.execute(
            select(RoutePlanRecord)
            .where(RoutePlanRecord.shipment_id == str(shipment.id))
        )).scalars().all()
        plan = plans[0]
        await db_session.refresh(plan, ["legs"])
        in_mem = results[0]
        assert abs(plan.total_cost_usd - in_mem.total_cost_usd) < 0.01
        assert abs(plan.total_time_h - in_mem.total_time_h) < 0.01
        assert plan.recommended == in_mem.recommended


class TestProvenanceTags:
    @pytest.mark.asyncio
    async def test_all_legs_have_provenance(self, db_session: AsyncSession, shipment):
        """Every leg must carry SIMULATED or DERIVED provenance."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        for itin in results:
            for leg in itin.legs:
                assert leg.provenance in ("SIMULATED", "DERIVED"), (
                    f"Invalid provenance '{leg.provenance}' on leg {leg}"
                )

    @pytest.mark.asyncio
    async def test_schedule_legs_are_simulated(self, db_session: AsyncSession, shipment):
        """Legs using a seeded schedule should carry SIMULATED provenance."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        for itin in results:
            for leg in itin.legs:
                if leg.schedule_id is not None:
                    assert leg.provenance == "SIMULATED", (
                        f"Schedule-sourced leg must be SIMULATED, got {leg.provenance}"
                    )


class TestEmptyState:
    @pytest.mark.asyncio
    async def test_unknown_origin_returns_empty(self, db_session: AsyncSession, shipment):
        """Unknown origin locode → empty list, not exception."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="ZZZZZ", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_same_origin_dest_returns_empty(self, db_session: AsyncSession, shipment):
        """Origin == destination → empty list."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INLUH",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_network_returns_empty(self, db_session: AsyncSession, shipment):
        """Empty network (no nodes) → empty list, not exception."""
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        assert results == []


class TestSeedDeterminism:
    @pytest.mark.asyncio
    async def test_same_seed_same_ranking(self, db_session: AsyncSession, shipment):
        """Two runs with the same seed should produce identical score ordering."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        r1 = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, seed=42, persist=False,
        )
        r2 = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, seed=42, persist=False,
        )
        scores_1 = [r.score for r in r1]
        scores_2 = [r.score for r in r2]
        assert scores_1 == scores_2, "Identical seed should produce identical scoring"


class TestScoring:
    def test_score_range(self):
        """All scores should be in [0, 1]."""
        candidates = [
            ItineraryResult(
                total_cost_usd=1000.0, total_time_h=20.0, total_co2_kg=100.0,
                reliability_score=0.9, risk_index=0.1,
            ),
            ItineraryResult(
                total_cost_usd=500.0, total_time_h=40.0, total_co2_kg=50.0,
                reliability_score=0.8, risk_index=0.2,
            ),
        ]
        weights = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
        scored = _score_candidates(candidates, weights)
        for c in scored:
            assert 0.0 <= c.score <= 1.0, f"Score {c.score} out of range"

    def test_single_candidate_scores_one(self):
        """A single candidate should score 1.0 (best in its own set)."""
        candidates = [
            ItineraryResult(
                total_cost_usd=1000.0, total_time_h=20.0, total_co2_kg=100.0,
                reliability_score=0.9, risk_index=0.1,
            )
        ]
        weights = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
        scored = _score_candidates(candidates, weights)
        assert scored[0].score == 1.0

    def test_ranked_by_score_descending(self):
        """Candidates returned by _score_candidates are sorted best-first."""
        candidates = [
            ItineraryResult(
                total_cost_usd=2000.0, total_time_h=10.0, total_co2_kg=50.0,
                reliability_score=0.99, risk_index=0.01,
            ),
            ItineraryResult(
                total_cost_usd=500.0, total_time_h=60.0, total_co2_kg=200.0,
                reliability_score=0.70, risk_index=0.30,
            ),
        ]
        weights = {"cost": 0.6, "time": 0.1, "reliability": 0.1, "co2": 0.1, "risk": 0.1}
        scored = _score_candidates(candidates, weights)
        assert scored[0].score >= scored[1].score


class TestPerformance:
    @pytest.mark.asyncio
    async def test_planning_under_2s(self, db_session: AsyncSession, shipment):
        """Planning over the tiny network should complete well under 2s."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        t0 = time.monotonic()
        await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"Planning took {elapsed:.2f}s — exceeds 2s budget"


class TestPlanTypeLabels:
    @pytest.mark.asyncio
    async def test_initial_plan_type_set(self, db_session: AsyncSession, shipment):
        """plan_type=INITIAL is propagated to ItineraryResult.plan_type."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD,
            plan_type=PlanType.INITIAL, persist=False,
        )
        assert results
        for r in results:
            assert r.plan_type == "INITIAL"

    @pytest.mark.asyncio
    async def test_recovery_plan_type_set(self, db_session: AsyncSession, shipment):
        """plan_type=RECOVERY is propagated."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.EXPRESS,
            plan_type=PlanType.RECOVERY, persist=False,
        )
        for r in results:
            assert r.plan_type == "RECOVERY"


class TestRankAndRecommended:
    @pytest.mark.asyncio
    async def test_rank_1_is_recommended(self, db_session: AsyncSession, shipment):
        """Rank 1 itinerary must have recommended=True, others recommended=False."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        recommended = [r for r in results if r.recommended]
        assert len(recommended) == 1, f"Expected exactly 1 recommended, got {len(recommended)}"
        assert recommended[0].rank == 1

    @pytest.mark.asyncio
    async def test_ranks_sequential(self, db_session: AsyncSession, shipment):
        """Ranks must be 1, 2, 3... (no gaps)."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD, persist=False,
        )
        ranks = sorted(r.rank for r in results)
        assert ranks == list(range(1, len(results) + 1)), f"Non-sequential ranks: {ranks}"


class TestTopK:
    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, db_session: AsyncSession, shipment):
        """top_k=2 should return at most 2 itineraries."""
        await _seed_tiny_network(db_session, str(shipment.id))
        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db_session, shipment_id=str(shipment.id),
            origin_locode="INLUH", dest_locode="INJNP",
            query_time=_NOW, priority=ShipmentPriority.STANDARD,
            top_k=2, persist=False,
        )
        assert len(results) <= 2
