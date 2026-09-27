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

    # Ensure a connected path from 0 to num_nodes - 1
    path = list(range(num_nodes))
    random.shuffle(path)
    path.remove(0)
    path.remove(num_nodes - 1)
    path = [0] + path + [num_nodes - 1]

    all_pairs = set()
    for i in range(len(path) - 1):
        all_pairs.add((path[i], path[i + 1]))

    # Add more random edges (forward only to avoid loops for simple enumeration)
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


def get_all_simple_paths(nodes, edges_by_from, schedules_by_edge):
    # DFS to find all valid path sequences of edges
    origin = 0
    dest = max(nodes.keys())
    
    all_paths = []
    
    def dfs(curr_node, current_time, path_legs, visited):
        if curr_node == dest:
            all_paths.append(list(path_legs))
            return
            
        if curr_node in visited:
            return
            
        visited.add(curr_node)
        
        for edge in edges_by_from.get(curr_node, []):
            leg = _compute_leg_kpis(edge, None, current_time, TEST_CARGO_WEIGHT_T)
            if leg:
                path_legs.append(leg)
                dfs(edge.to_id, leg.arrival_at, path_legs, visited)
                path_legs.pop()
                
        visited.remove(curr_node)
        
    dfs(origin, TEST_QUERY_TIME, [], set())
    return all_paths


def dominates(v1, v2):
    """Returns True if v1 dominates v2.
    Vectors are (cost, time, co2, risk). Lower is better for all.
    v1 dominates v2 if v1 <= v2 on all axes AND v1 < v2 on at least one.
    """
    less_eq = all(a <= b for a, b in zip(v1, v2))
    strictly_less = any(a < b for a, b in zip(v1, v2))
    return less_eq and strictly_less


@pytest.mark.xfail(strict=True, reason="FINDING-3C-1: Yen k-shortest can return dominated itineraries (single-axis optimum); planner fix is a separate wave")
@pytest.mark.parametrize("seed", [101, 102, 103, 104, 105])
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_pareto_soundness_seed(mock_params, seed):
    nodes, edges_by_from, schedules_by_edge, transshipments = make_random_graph(seed, 6)
    origin = 0
    dest = max(nodes.keys())
    
    yen_paths = _yen_k_shortest(
        origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
        TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=5
    )
    
    all_simple_paths = get_all_simple_paths(nodes, edges_by_from, schedules_by_edge)
    all_vectors = [evaluate_path(p) for p in all_simple_paths]
    
    # Property A: every returned itinerary is non-dominated in 4-axis space versus ALL enumerated simple paths.
    for yen_path in yen_paths:
        yen_vec = evaluate_path(yen_path)
        for cand_vec in all_vectors:
            if dominates(cand_vec, yen_vec):
                pytest.fail(f"Yen path dominated! Yen: {yen_vec}, Dominating: {cand_vec}, seed: {seed}")


@pytest.mark.parametrize("seed", [201, 202, 203, 204, 205])
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_pareto_top_pick_nondominated(mock_params, seed):
    nodes, edges_by_from, schedules_by_edge, transshipments = make_random_graph(seed, 6)
    origin = 0
    dest = max(nodes.keys())
    
    yen_paths = _yen_k_shortest(
        origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
        TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=5
    )
    
    all_simple_paths = get_all_simple_paths(nodes, edges_by_from, schedules_by_edge)
    all_vectors = [evaluate_path(p) for p in all_simple_paths]
    
    if not yen_paths:
        return
        
    itins = []
    for p in yen_paths:
        c, t, co2, r = evaluate_path(p)
        itin = ItineraryResult(legs=p, total_cost_usd=c, total_time_h=t, total_co2_kg=co2, risk_index=r)
        itins.append(itin)
        
    weights = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
    for itin in itins:
        itin.reliability_score = math.prod(leg.reliability for leg in itin.legs)
        
    scored = _score_candidates(itins, weights)
    top_pick = max(scored, key=lambda x: x.score)
    top_vec = (top_pick.total_cost_usd, top_pick.total_time_h, top_pick.total_co2_kg, top_pick.risk_index)
    
    for cand_vec in all_vectors:
        if dominates(cand_vec, top_vec):
            pytest.fail(f"Top pick dominated! Top: {top_vec}, Dominating: {cand_vec}, seed: {seed}")
