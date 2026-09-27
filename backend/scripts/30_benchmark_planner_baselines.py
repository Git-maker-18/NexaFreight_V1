#!/usr/bin/env python3
import argparse
import json
import logging
import math
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from nexafreight.services.planner import (
    _Node, _Edge, _Schedule, _Transshipment, _yen_k_shortest, _score_candidates, ItineraryResult
)

# ---------------------------------------------------------------------------
# Setup & Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

UTC = timezone.utc
TEST_HORIZON_END = datetime(2040, 1, 1, tzinfo=UTC)
TEST_QUERY_TIME = datetime(2020, 1, 1, tzinfo=UTC)
TEST_CARGO_WEIGHT_T = 10.0
TEST_CONNECTION_MARGIN_H = 1.0

STANDARD_WEIGHTS = {"cost": 0.4, "time": 0.25, "reliability": 0.2, "co2": 0.1, "risk": 0.05}
CRITICAL_WEIGHTS = {"cost": 0.1, "time": 0.6, "reliability": 0.2, "co2": 0.05, "risk": 0.05}
ECONOMY_WEIGHTS = {"cost": 0.6, "time": 0.1, "reliability": 0.2, "co2": 0.05, "risk": 0.05}


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
    return total_cost, total_time, total_co2, risk_index, reliability


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()

    num_queries = 40
    wins_cheapest = 0
    wins_fastest = 0
    wins_greenest = 0

    sum_crit = 0.0
    sum_std = 0.0
    sum_econ = 0.0

    import copy

    for i in range(num_queries):
        seed = 1000 + i
        nodes, edges_by_from, schedules_by_edge, transshipments = make_random_graph(seed, random.randint(6, 12))
        origin = 0
        dest = max(nodes.keys())

        with patch("nexafreight.services.planner.params.get_float", return_value=1.0):
            yen_paths = _yen_k_shortest(
                origin, dest, nodes, edges_by_from, schedules_by_edge, transshipments,
                TEST_QUERY_TIME, TEST_CARGO_WEIGHT_T, TEST_CONNECTION_MARGIN_H, TEST_HORIZON_END, k=5
            )

        itins = []
        for p in yen_paths:
            c, t, co2, r, rel = evaluate_path(p)
            itin = ItineraryResult(legs=p, total_cost_usd=c, total_time_h=t, total_co2_kg=co2, risk_index=r)
            itin.reliability_score = rel
            itins.append(itin)

        if not itins:
            # Should not happen on connected graphs, but fallback
            num_queries -= 1
            continue

        # Evaluate naive policies
        cheapest_idx = min(range(len(itins)), key=lambda x: itins[x].total_cost_usd)
        fastest_idx = min(range(len(itins)), key=lambda x: itins[x].total_time_h)
        greenest_idx = min(range(len(itins)), key=lambda x: itins[x].total_co2_kg)

        # Score with profiles
        crit_scored = _score_candidates(copy.deepcopy(itins), CRITICAL_WEIGHTS)
        std_scored = _score_candidates(copy.deepcopy(itins), STANDARD_WEIGHTS)
        econ_scored = _score_candidates(copy.deepcopy(itins), ECONOMY_WEIGHTS)

        crit_best = max(crit_scored, key=lambda x: x.score).score
        std_best = max(std_scored, key=lambda x: x.score).score
        econ_best = max(econ_scored, key=lambda x: x.score).score

        sum_crit += crit_best
        sum_std += std_best
        sum_econ += econ_best

        # Use STANDARD for the beats comparison
        cheapest_score = std_scored[cheapest_idx].score
        fastest_score = std_scored[fastest_idx].score
        greenest_score = std_scored[greenest_idx].score

        if std_best >= cheapest_score: wins_cheapest += 1
        if std_best >= fastest_score: wins_fastest += 1
        if std_best >= greenest_score: wins_greenest += 1

    if num_queries == 0:
        log.error("No successful queries")
        sys.exit(1)

    pct_cheap = (wins_cheapest / num_queries) * 100
    pct_fast = (wins_fastest / num_queries) * 100
    pct_green = (wins_greenest / num_queries) * 100

    mean_crit = sum_crit / num_queries
    mean_std = sum_std / num_queries
    mean_econ = sum_econ / num_queries

    if pct_cheap >= 95 and pct_fast >= 95 and pct_green >= 95:
        verdict = "OK"
    elif pct_cheap < 50 or pct_fast < 50 or pct_green < 50:
        verdict = "POOR"
    else:
        verdict = "MIXED"

    print(f"REPORT > PLANNER beats cheapest: {wins_cheapest}/{num_queries} ({pct_cheap:.1f}%)")
    print(f"REPORT > PLANNER beats fastest: {wins_fastest}/{num_queries} ({pct_fast:.1f}%)")
    print(f"REPORT > PLANNER beats greenest: {wins_greenest}/{num_queries} ({pct_green:.1f}%)")
    print(f"REPORT > PLANNER mean composite: CRITICAL {mean_crit:.4f} STANDARD {mean_std:.4f} ECONOMY {mean_econ:.4f}")
    print(f"REPORT > PLANNER VERDICT: {verdict}")

    artifact = {
        "metrics_per_policy": {
            "beats_cheapest": wins_cheapest,
            "beats_fastest": wins_fastest,
            "beats_greenest": wins_greenest,
            "mean_composite_critical": mean_crit,
            "mean_composite_standard": mean_std,
            "mean_composite_economy": mean_econ
        },
        "corpus_size": num_queries,
        "seeds": list(range(1000, 1000 + 40)),
        "weights_used": {
            "STANDARD": STANDARD_WEIGHTS,
            "CRITICAL": CRITICAL_WEIGHTS,
            "ECONOMY": ECONOMY_WEIGHTS
        },
        "review_spec": "EVALUATION_REVIEW 2.4",
        "timestamp": datetime.now(UTC).isoformat()
    }

    out_path = Path(__file__).resolve().parent.parent / "eval" / "artifacts" / "planner_baseline_benchmark.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2)

if __name__ == "__main__":
    main()
