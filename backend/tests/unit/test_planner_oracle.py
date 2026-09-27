import datetime
import math
import random
from unittest.mock import patch
import networkx as nx
import pytest
from datetime import timezone, timedelta

from nexafreight.services.planner import (
    _Node,
    _Edge,
    _Schedule,
    _Transshipment,
    _dijkstra,
    _yen_k_shortest,
    LegKPI,
)

# Constants for synthetic data
UTC = timezone.utc
TEST_HORIZON_END = datetime.datetime(2040, 1, 1, tzinfo=UTC)
TEST_QUERY_TIME = datetime.datetime(2020, 1, 1, tzinfo=UTC)
TEST_CARGO_WEIGHT_T = 10.0
TEST_CONNECTION_MARGIN_H = 1.0


def make_random_graph(seed: int, num_nodes: int, num_edges: int):
    random.seed(seed)
    nodes = {}
    for i in range(num_nodes):
        nodes[i] = _Node(id=i, locode=f"LOC{i}", lat=0.0, lon=0.0, modes={"ROAD", "SEA", "RAIL", "AIR"})

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

    while len(all_pairs) < num_edges:
        u = random.randint(0, num_nodes - 1)
        v = random.randint(0, num_nodes - 1)
        if u != v:
            all_pairs.add((u, v))

    for u, v in all_pairs:
        cost = random.uniform(10.0, 1000.0)
        time_h = random.uniform(1.0, 100.0)
        co2 = random.uniform(10.0, 500.0)
        rel = random.uniform(0.5, 0.99)
        
        # We model everything as SEA to use schedules, or ROAD to skip schedules.
        # Let's just use schedules for all. The objective weights will be exactly the leg KPI.
        # But wait, LegKPI computation adds handling cost, time, etc.
        # It's easier to create predictable edge params or just use actual nx edge weight matching the planner's leg computation.
        
        # Actually, let's just make modes "ROAD" to avoid schedules? 
        # But wait, if mode="ROAD", _compute_leg_kpis uses transit_time = distance_km / speed.
        # Let's just use schedules for all edges to perfectly control departure and arrival times.
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

    # Transshipments (zero cost/time for simplicity, or small random)
    for i in range(num_nodes):
        transshipments[i] = _Transshipment(
            node_id=i, min_dwell_h=0.0, max_dwell_h=24.0, handling_cost_usd=random.uniform(0.0, 50.0)
        )

    return nodes, edges_by_from, schedules_by_edge, transshipments


def make_handcrafted_graph_1():
    # 0 -> 1 -> 2
    # 0 -> 2
    nodes = {
        0: _Node(0, "L0", 0, 0, {"SEA"}),
        1: _Node(1, "L1", 0, 0, {"SEA"}),
        2: _Node(2, "L2", 0, 0, {"SEA"}),
    }
    edges_by_from = {0: [], 1: [], 2: []}
    schedules_by_edge = {}
    transshipments = {
        0: _Transshipment(0, 0, 24, 10),
        1: _Transshipment(1, 0, 24, 20),
        2: _Transshipment(2, 0, 24, 10),
    }

    e1 = _Edge(1, 0, 1, "SEA", 100, "", "", "", None, 0.9, False)
    e2 = _Edge(2, 1, 2, "SEA", 100, "", "", "", None, 0.9, False)
    e3 = _Edge(3, 0, 2, "SEA", 300, "", "", "", None, 0.8, False)
    
    edges_by_from[0].extend([e1, e3])
    edges_by_from[1].append(e2)

    t0 = TEST_QUERY_TIME
    schedules_by_edge[1] = [_Schedule(1, 1, "S", t0, t0 + timedelta(hours=10), None, None, "")]
    schedules_by_edge[2] = [_Schedule(2, 2, "S", t0 + timedelta(hours=15), t0 + timedelta(hours=20), None, None, "")]
    schedules_by_edge[3] = [_Schedule(3, 3, "S", t0, t0 + timedelta(hours=30), None, None, "")]

    return nodes, edges_by_from, schedules_by_edge, transshipments


def make_handcrafted_graph_2():
    nodes, edges_by_from, schedules_by_edge, transshipments = make_handcrafted_graph_1()
    nodes[3] = _Node(3, "L3", 0, 0, {"SEA"})
    edges_by_from[3] = []
    transshipments[3] = _Transshipment(3, 0, 24, 0)
    e4 = _Edge(4, 2, 3, "SEA", 50, "", "", "", None, 0.95, False)
    edges_by_from[2].append(e4)
    t0 = TEST_QUERY_TIME
    schedules_by_edge[4] = [_Schedule(4, 4, "S", t0 + timedelta(hours=25), t0 + timedelta(hours=30), None, None, "")]
    return nodes, edges_by_from, schedules_by_edge, transshipments


def _get_graphs():
    graphs = []
    for seed in [42, 43, 44, 45, 46, 47]:
        graphs.append(make_random_graph(seed, num_nodes=random.Random(seed).randint(6, 10), num_edges=random.Random(seed).randint(10, 18)))
    graphs.append(make_handcrafted_graph_1())
    graphs.append(make_handcrafted_graph_2())
    return graphs


from nexafreight.services.planner import _compute_leg_kpis

def _leg_objective(leg, objective):
    if objective == "cost":
        return leg.cost_usd
    elif objective == "time":
        return leg.transit_h
    elif objective == "co2":
        return leg.co2_kg
    elif objective == "reliability":
        return -math.log(max(1e-9, leg.reliability))
    return leg.cost_usd


def get_nx_graph(nodes, edges_by_from, schedules_by_edge, transshipments, objective, query_time):
    G = nx.DiGraph()
    for n in nodes.values():
        G.add_node(n.id)

    # For each edge, compute the leg KPI assuming departure happens immediately at query_time
    # This matches the "one schedule far in the future" setup where time windows don't bind,
    # or where we just want the edge weight.
    for u, edges in edges_by_from.items():
        for e in edges:
            # We created exactly one schedule per edge, or none if ROAD
            scheds = schedules_by_edge.get(e.id, [])
            sched = scheds[0] if scheds else None
            # connection_margin_h doesn't matter because we just call _compute_leg_kpis
            # wait, earliest_dep is passed, but it just copies schedule departure!
            leg = _compute_leg_kpis(e, sched, query_time, TEST_CARGO_WEIGHT_T)
            weight = _leg_objective(leg, objective)
            # Add edge to DiGraph
            G.add_edge(u, e.to_id, weight=weight)
            
    return G


@pytest.mark.parametrize("graph_idx", range(8))
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_oracle_cost(mock_params, graph_idx):
    _run_oracle_objective(graph_idx, "cost")

@pytest.mark.parametrize("graph_idx", range(8))
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_oracle_time(mock_params, graph_idx):
    _run_oracle_objective(graph_idx, "time")

@pytest.mark.parametrize("graph_idx", range(8))
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_oracle_co2(mock_params, graph_idx):
    _run_oracle_objective(graph_idx, "co2")

@pytest.mark.parametrize("graph_idx", range(8))
@patch("nexafreight.services.planner.params.get_float", return_value=1.0)
def test_oracle_reliability(mock_params, graph_idx):
    _run_oracle_objective(graph_idx, "reliability")


def _run_oracle_objective(graph_idx, objective):
    graphs = _get_graphs()
    nodes, edges_by_from, schedules_by_edge, transshipments = graphs[graph_idx]
    
    origin = 0
    dest = max(nodes.keys())

    G = get_nx_graph(nodes, edges_by_from, schedules_by_edge, transshipments, objective, TEST_QUERY_TIME)
    
    path = _dijkstra(
        origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
        TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END,
        objective=objective, max_depth=20
    )
    
    assert path is not None, "Planner could not find a path"
    
    planner_total = sum(_leg_objective(leg, objective) for leg in path)
    
    nx_total = nx.shortest_path_length(G, source=origin, target=dest, weight="weight")
    assert math.isclose(planner_total, nx_total, rel_tol=1e-6), f"Planner obj {planner_total} != nx {nx_total}"


def test_oracle_yen_matches_dijkstra():
    graphs = _get_graphs()
    nodes, edges_by_from, schedules_by_edge, transshipments = graphs[6]
    
    origin = 0
    dest = max(nodes.keys())
    
    with patch("nexafreight.services.planner.params.get_float", return_value=1.0):
        yen_paths = _yen_k_shortest(
            origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
            TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=5
        )
        assert len(yen_paths) > 0

        for objective in ["cost", "time", "co2", "reliability"]:
            d_path = _dijkstra(
                origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
                TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END,
                objective=objective, max_depth=20
            )
            assert d_path is not None
            d_best = sum(_leg_objective(leg, objective) for leg in d_path)
            
            yen_best = min(sum(_leg_objective(leg, objective) for leg in yp) for yp in yen_paths)
            
            assert math.isclose(d_best, yen_best, rel_tol=1e-6)
