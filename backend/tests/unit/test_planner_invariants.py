import datetime
import math
import random
from unittest.mock import patch
import pytest
from datetime import timezone, timedelta

from nexafreight.services.planner import (
    _Node, _Edge, _Schedule, _Transshipment, _yen_k_shortest, _score_candidates, ItineraryResult, LegKPI, _compute_leg_kpis
)

UTC = timezone.utc
TEST_HORIZON_END = datetime.datetime(2040, 1, 1, tzinfo=UTC)
TEST_QUERY_TIME = datetime.datetime(2020, 1, 1, tzinfo=UTC)
TEST_CARGO_WEIGHT_T = 10.0
TEST_CONNECTION_MARGIN_H = 1.0


def make_random_graph(seed: int, num_nodes: int):
    random.seed(seed)
    nodes = {}
    for i in range(num_nodes):
        nodes[i] = _Node(id=i, locode=f"LOC{i}", lat=0.0, lon=0.0, modes={"ROAD"})

    edges_by_from = {i: [] for i in range(num_nodes)}
    schedules_by_edge = {}
    transshipments = {}
    edge_id = 0

    path = list(range(num_nodes))
    random.shuffle(path)
    path.remove(0)
    path.remove(num_nodes - 1)
    path = [0] + path + [num_nodes - 1]

    all_pairs = set()
    for i in range(len(path) - 1):
        all_pairs.add((path[i], path[i + 1]))

    for u in range(num_nodes):
        for v in range(u + 1, num_nodes):
            if random.random() < 0.5:
                all_pairs.add((u, v))

    for u, v in all_pairs:
        rel = random.uniform(0.5, 0.99)
        e = _Edge(
            id=edge_id,
            from_id=u,
            to_id=v,
            mode="ROAD",
            distance_km=random.uniform(10.0, 500.0),
            speed_param="foo",
            cost_param="bar",
            co2_param="baz",
            capacity_teu=None,
            reliability=rel,
            is_dfc=False,
        )
        edges_by_from[u].append(e)
        schedules_by_edge[edge_id] = []
        edge_id += 1

    for i in range(num_nodes):
        transshipments[i] = _Transshipment(
            node_id=i, min_dwell_h=0.0, max_dwell_h=24.0, handling_cost_usd=random.uniform(0.0, 50.0)
        )

    return nodes, edges_by_from, schedules_by_edge, transshipments


def evaluate_path(path_legs):
    total_cost = sum(leg.cost_usd for leg in path_legs)
    total_time = sum(leg.transit_h for leg in path_legs)
    total_co2 = sum(leg.co2_kg for leg in path_legs)
    reliability = math.prod(leg.reliability for leg in path_legs) if path_legs else 1.0
    risk_index = round(1.0 - reliability, 4)
    return total_cost, total_time, total_co2, risk_index


@pytest.fixture
def invariant_data():
    nodes, edges_by_from, schedules_by_edge, transshipments = make_random_graph(42, 10)
    origin = 0
    dest = max(nodes.keys())
    
    with patch("nexafreight.services.planner.params.get_float", return_value=1.0):
        yen_paths = _yen_k_shortest(
            origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
            TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=20
        )
        
    itins = []
    for p in yen_paths:
        c, t, co2, r = evaluate_path(p)
        itin = ItineraryResult(legs=p, total_cost_usd=c, total_time_h=t, total_co2_kg=co2, risk_index=r)
        itin.reliability_score = math.prod(leg.reliability for leg in itin.legs)
        itins.append(itin)
        
    return nodes, edges_by_from, schedules_by_edge, transshipments, itins


def test_critical_beats_standard_on_time(invariant_data):
    _, _, _, _, itins = invariant_data
    
    standard_weights = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
    critical_weights = {"cost": 0.1, "time": 0.6, "reliability": 0.2, "co2": 0.05, "risk": 0.05}
    
    # We must copy itineraries because score is mutated
    import copy
    st_itins = copy.deepcopy(itins)
    cr_itins = copy.deepcopy(itins)
    
    st_scored = _score_candidates(st_itins, standard_weights)
    cr_scored = _score_candidates(cr_itins, critical_weights)
    
    st_pick = max(st_scored, key=lambda x: x.score)
    cr_pick = max(cr_scored, key=lambda x: x.score)
    
    assert cr_pick.total_time_h <= st_pick.total_time_h


def test_economy_cheaper_than_critical(invariant_data):
    _, _, _, _, itins = invariant_data
    
    critical_weights = {"cost": 0.1, "time": 0.6, "reliability": 0.2, "co2": 0.05, "risk": 0.05}
    economy_weights = {"cost": 0.6, "time": 0.1, "reliability": 0.2, "co2": 0.05, "risk": 0.05}
    
    import copy
    cr_itins = copy.deepcopy(itins)
    ec_itins = copy.deepcopy(itins)
    
    cr_scored = _score_candidates(cr_itins, critical_weights)
    ec_scored = _score_candidates(ec_itins, economy_weights)
    
    cr_pick = max(cr_scored, key=lambda x: x.score)
    ec_pick = max(ec_scored, key=lambda x: x.score)
    
    assert ec_pick.total_cost_usd <= cr_pick.total_cost_usd


def test_seed_determinism_score(invariant_data):
    _, _, _, _, itins = invariant_data
    standard_weights = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
    
    import copy
    run1 = _score_candidates(copy.deepcopy(itins), standard_weights)
    run2 = _score_candidates(copy.deepcopy(itins), standard_weights)
    
    run1.sort(key=lambda x: x.score, reverse=True)
    run2.sort(key=lambda x: x.score, reverse=True)
    
    keys1 = [r.structural_key for r in run1]
    keys2 = [r.structural_key for r in run2]
    
    assert keys1 == keys2


def test_seed_determinism_yen():
    nodes, edges_by_from, schedules_by_edge, transshipments = make_random_graph(99, 8)
    origin = 0
    dest = max(nodes.keys())
    
    with patch("nexafreight.services.planner.params.get_float", return_value=1.0):
        yen_paths1 = _yen_k_shortest(
            origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
            TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=10
        )
        yen_paths2 = _yen_k_shortest(
            origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
            TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=10
        )
        
    keys1 = [tuple(leg.structural_key for leg in p) for p in yen_paths1]
    keys2 = [tuple(leg.structural_key for leg in p) for p in yen_paths2]
    
    assert keys1 == keys2
