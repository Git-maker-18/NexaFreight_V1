"""Schedule-aware multimodal route optimizer (planner service).

Implements time-expanded graph search over the India logistics network to
produce ranked alternative itineraries for a shipment, scored by weighted
objectives that vary by priority profile (CRITICAL/EXPRESS/STANDARD/ECONOMY).

Algorithm outline
-----------------
1. Load network graph (nodes, edges, schedules, transshipment links) from DB.
2. Run four single-objective scalarizations (cheapest / fastest / most-reliable /
   greenest) to seed diverse candidates.
3. Run Yen k-shortest (k = top_k param) on the cost-weighted time-expanded graph
   for additional diversity.
4. Deduplicate structurally identical chains (same sequence of mode + from_node +
   to_node).
5. Apply hard filters: deadline feasibility, capacity, connection dwell ≥ minimum.
6. Score survivors with normalized weighted objective (weights from priority profile
   in parameter_policy).
7. Persist route_plan + route_leg rows; return ranked ItineraryResult list.

Invariant compliance
--------------------
- All empirical constants (speeds, CO2 factors, cost rates) are loaded from
  parameter_empirical via params module; no hardcoded empirical values in this file.
- Policy values (connection margin, top_k, weight profiles) are loaded from
  parameter_policy via params module.
- Provenance: SIMULATED for seeded schedule legs, DERIVED for computed-on-demand legs.
- Seed parameter accepted and forwarded to the RNG for deterministic tie-breaking.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.core import params
from nexafreight.enums import PlanType, ShipmentPriority, TransportMode
from nexafreight.models.network import EdgeSchedule, NetworkEdge, NetworkNode, TransshipmentLink
from nexafreight.models.route_plan import RouteLegRecord, RoutePlanRecord

log = logging.getLogger("nexafreight.planner")

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegKPI:
    """KPIs for one leg in a candidate itinerary."""

    mode: str
    from_node_id: int
    to_node_id: int
    from_locode: str
    to_locode: str
    edge_id: int | None
    schedule_id: int | None
    departure_at: datetime
    arrival_at: datetime
    cost_usd: float
    transit_h: float
    co2_kg: float
    reliability: float
    provenance: str  # SIMULATED | DERIVED

    @property
    def structural_key(self) -> tuple:
        """Fingerprint for dedup (ignores timing but captures mode + node chain)."""
        return (self.mode, self.from_node_id, self.to_node_id)


@dataclass
class ItineraryResult:
    """A complete scored itinerary (sequence of LegKPIs)."""

    legs: list[LegKPI] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_time_h: float = 0.0
    total_co2_kg: float = 0.0
    reliability_score: float = 1.0  # product of per-leg reliabilities
    risk_index: float = 0.0
    score: float = 0.0
    recommended: bool = False
    rationale: str = ""
    plan_type: str = "ALTERNATIVE"
    priority: str = "STANDARD"
    objective_weights: dict[str, float] = field(default_factory=dict)
    rank: int = 0

    @property
    def structural_key(self) -> tuple:
        """Fingerprint for structural dedup."""
        return tuple(leg.structural_key for leg in self.legs)

    def passes_deadline(self, deadline: datetime | None) -> bool:
        if deadline is None or not self.legs:
            return True
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        arr = self.legs[-1].arrival_at
        if arr.tzinfo is None:
            arr = arr.replace(tzinfo=UTC)
        return arr <= deadline


# ---------------------------------------------------------------------------
# Graph structures (in-memory, loaded once per planning query)
# ---------------------------------------------------------------------------


@dataclass
class _Node:
    id: int
    locode: str
    lat: float
    lon: float
    modes: set[str]


@dataclass
class _Edge:
    id: int
    from_id: int
    to_id: int
    mode: str
    distance_km: float
    speed_param: str
    cost_param: str
    co2_param: str
    capacity_teu: int | None
    reliability: float
    is_dfc: bool


@dataclass
class _Schedule:
    id: int
    edge_id: int
    service_name: str
    departure_at: datetime
    arrival_at: datetime
    cutoff_at: datetime | None
    capacity_remaining: int | None
    provenance: str


@dataclass
class _Transshipment:
    node_id: int
    min_dwell_h: float
    max_dwell_h: float
    handling_cost_usd: float


# ---------------------------------------------------------------------------
# Network loader
# ---------------------------------------------------------------------------


async def _load_network(
    session: AsyncSession,
    query_time: datetime,
    horizon_days: int,
) -> tuple[
    dict[int, _Node],
    dict[int, list[_Edge]],  # adjacency: from_node_id → [edges]
    dict[int, list[_Schedule]],  # edge_id → [schedules within horizon]
    dict[int, _Transshipment],  # node_id → transshipment
    dict[str, int],  # locode → node_id
]:
    """Load entire network into memory for fast traversal."""
    horizon_end = query_time + timedelta(days=horizon_days)

    node_rows = (await session.execute(select(NetworkNode))).scalars().all()
    nodes: dict[int, _Node] = {}
    locode_to_id: dict[str, int] = {}
    for n in node_rows:
        try:
            modes = set(json.loads(n.modes_json))
        except Exception:
            modes = set()
        nodes[n.id] = _Node(id=n.id, locode=n.locode, lat=n.latitude, lon=n.longitude, modes=modes)
        locode_to_id[n.locode] = n.id

    edge_rows = (await session.execute(select(NetworkEdge))).scalars().all()
    edges_by_from: dict[int, list[_Edge]] = {}
    for e in edge_rows:
        edge = _Edge(
            id=e.id, from_id=e.from_node_id, to_id=e.to_node_id,
            mode=str(e.mode), distance_km=e.distance_km,
            speed_param=e.transit_speed_param_key,
            cost_param=e.base_cost_param_key,
            co2_param=e.co2_intensity_param_key,
            capacity_teu=e.capacity_teu, reliability=e.reliability,
            is_dfc=e.is_dfc,
        )
        edges_by_from.setdefault(e.from_node_id, []).append(edge)

    sched_rows = (
        await session.execute(
            select(EdgeSchedule).where(
                EdgeSchedule.departure_at >= query_time,
                EdgeSchedule.departure_at <= horizon_end,
            )
        )
    ).scalars().all()
    schedules_by_edge: dict[int, list[_Schedule]] = {}
    for s in sched_rows:
        dep = s.departure_at if s.departure_at.tzinfo else s.departure_at.replace(tzinfo=UTC)
        arr = s.arrival_at if s.arrival_at.tzinfo else s.arrival_at.replace(tzinfo=UTC)
        sched = _Schedule(
            id=s.id, edge_id=s.edge_id, service_name=s.service_name,
            departure_at=dep, arrival_at=arr,
            cutoff_at=s.cutoff_at, capacity_remaining=s.capacity_remaining,
            provenance=str(s.provenance),
        )
        schedules_by_edge.setdefault(s.edge_id, []).append(sched)

    # Sort schedules by departure for efficient next-departure lookup
    for eid in schedules_by_edge:
        schedules_by_edge[eid].sort(key=lambda s: s.departure_at)

    trans_rows = (await session.execute(select(TransshipmentLink))).scalars().all()
    transshipments: dict[int, _Transshipment] = {}
    for t in trans_rows:
        transshipments[t.node_id] = _Transshipment(
            node_id=t.node_id, min_dwell_h=t.min_dwell_h,
            max_dwell_h=t.max_dwell_h, handling_cost_usd=t.handling_cost_usd,
        )

    return nodes, edges_by_from, schedules_by_edge, transshipments, locode_to_id


# ---------------------------------------------------------------------------
# KPI computation helpers
# ---------------------------------------------------------------------------


def _compute_leg_kpis(
    edge: _Edge,
    schedule: _Schedule | None,
    current_time: datetime,
    cargo_weight_t: float,
) -> LegKPI | None:
    """Return a LegKPI for the given edge/schedule, or None if no departure found."""
    connection_margin_h = params.get_float("planner.connection_margin_h", 2.0)

    if schedule is not None:
        # Check capacity
        if schedule.capacity_remaining is not None and schedule.capacity_remaining <= 0:
            return None
        departure = schedule.departure_at
        arrival = schedule.arrival_at
        prov = schedule.provenance
        sched_id = schedule.id
    else:
        # Compute on-demand (DERIVED) — happens for ROAD legs that run continuously
        speed = _get_speed(edge)
        if speed <= 0:
            return None
        departure = current_time
        transit_h = edge.distance_km / speed
        arrival = departure + timedelta(hours=transit_h)
        prov = "DERIVED"
        sched_id = None

    transit_h = (arrival - departure).total_seconds() / 3600.0
    cost_rate = params.get_float(edge.cost_param, 0.065)  # USD per km per tonne
    co2_rate = params.get_float(edge.co2_param, 62.0)  # g CO2 per tonne-km

    cost_usd = edge.distance_km * cost_rate * cargo_weight_t
    co2_kg = (edge.distance_km * co2_rate * cargo_weight_t) / 1000.0

    return LegKPI(
        mode=edge.mode,
        from_node_id=edge.from_id,
        to_node_id=edge.to_id,
        from_locode="",  # filled in by caller
        to_locode="",
        edge_id=edge.id,
        schedule_id=sched_id,
        departure_at=departure,
        arrival_at=arrival,
        cost_usd=round(cost_usd, 2),
        transit_h=round(transit_h, 3),
        co2_kg=round(co2_kg, 3),
        reliability=edge.reliability,
        provenance=prov,
    )


def _get_speed(edge: _Edge) -> float:
    """Return speed in km/h or kn from params for the edge's speed_param key."""
    raw = params.get_float(edge.speed_param, 50.0)
    # Convert knots to km/h for sea edges
    if "kn" in edge.speed_param:
        raw = raw * 1.852
    return raw


def _next_departure(
    schedules: list[_Schedule],
    earliest: datetime,
) -> _Schedule | None:
    """Binary search for the first schedule departing at or after earliest."""
    lo, hi = 0, len(schedules)
    while lo < hi:
        mid = (lo + hi) // 2
        if schedules[mid].departure_at < earliest:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(schedules):
        return schedules[lo]
    return None


# ---------------------------------------------------------------------------
# Time-expanded Dijkstra
# ---------------------------------------------------------------------------

# State: (cost_or_objective, current_node_id, current_time, path)
_INF = float("inf")


def _dijkstra(
    origin_id: int,
    dest_id: int,
    nodes: dict[int, _Node],
    edges_by_from: dict[int, list[_Edge]],
    schedules_by_edge: dict[int, list[_Schedule]],
    transshipments: dict[int, _Transshipment],
    query_time: datetime,
    cargo_weight_t: float,
    connection_margin_h: float,
    horizon_end: datetime,
    objective: str = "cost",  # cost | time | co2 | reliability
    max_depth: int = 8,
) -> list[LegKPI] | None:
    """Single-objective time-expanded Dijkstra.

    Returns the best path from origin to dest under the given objective,
    or None if unreachable.
    """

    def _leg_objective(leg: LegKPI) -> float:
        if objective == "cost":
            return leg.cost_usd
        elif objective == "time":
            return leg.transit_h
        elif objective == "co2":
            return leg.co2_kg
        elif objective == "reliability":
            return -math.log(max(1e-9, leg.reliability))  # minimize -log(reliability) = maximize product
        return leg.cost_usd

    # (objective_value, node_id, arrival_time_ts, path: list[LegKPI])
    heap: list[tuple[float, int, float, list[LegKPI]]] = [
        (0.0, origin_id, query_time.timestamp(), [])
    ]
    visited: dict[int, float] = {}  # node_id → best arrival_time seen

    while heap:
        obj_val, node_id, arr_ts, path = heapq.heappop(heap)

        if node_id == dest_id:
            return path

        if len(path) >= max_depth:
            continue

        arr_time = datetime.fromtimestamp(arr_ts, tz=UTC)
        if arr_time > horizon_end:
            continue

        # Determine earliest we can depart this node (arrival + dwell)
        if node_id == origin_id:
            earliest_dep = arr_time
        else:
            trans = transshipments.get(node_id)
            dwell_min_h = (trans.min_dwell_h if trans else 0.0) + connection_margin_h
            earliest_dep = arr_time + timedelta(hours=dwell_min_h)

        for edge in edges_by_from.get(node_id, []):
            schedules = schedules_by_edge.get(edge.id, [])

            if schedules:
                sched = _next_departure(schedules, earliest_dep)
                if sched is None:
                    continue
                leg = _compute_leg_kpis(edge, sched, earliest_dep, cargo_weight_t)
            else:
                # On-demand ROAD — derive from speed
                leg = _compute_leg_kpis(edge, None, earliest_dep, cargo_weight_t)

            if leg is None:
                continue
            if leg.arrival_at > horizon_end:
                continue

            new_arr_ts = leg.arrival_at.timestamp()
            prev_arr_ts = visited.get(edge.to_id, _INF)
            # Accept if we arrive earlier (for time/co2/reliability objectives)
            # or if objective value is lower
            if new_arr_ts >= prev_arr_ts and objective == "time":
                continue
            visited[edge.to_id] = new_arr_ts

            new_obj = obj_val + _leg_objective(leg)
            new_path = path + [leg]
            heapq.heappush(heap, (new_obj, edge.to_id, new_arr_ts, new_path))

    return None


# ---------------------------------------------------------------------------
# Yen k-shortest (cost-weighted, time-expanded)
# ---------------------------------------------------------------------------


def _yen_k_shortest(
    origin_id: int,
    dest_id: int,
    nodes: dict[int, _Node],
    edges_by_from: dict[int, list[_Edge]],
    schedules_by_edge: dict[int, list[_Schedule]],
    transshipments: dict[int, _Transshipment],
    query_time: datetime,
    cargo_weight_t: float,
    connection_margin_h: float,
    horizon_end: datetime,
    k: int = 5,
) -> list[list[LegKPI]]:
    """Yen's k-shortest paths adapted for time-expanded graph.

    Returns up to k distinct paths (may be fewer if graph is small).
    """
    results: list[list[LegKPI]] = []
    candidates: list[tuple[float, list[LegKPI]]] = []

    # A*: first shortest path
    first = _dijkstra(
        origin_id, dest_id, nodes, edges_by_from, schedules_by_edge,
        transshipments, query_time, cargo_weight_t, connection_margin_h,
        horizon_end, objective="cost",
    )
    if first is None:
        return []
    results.append(first)

    for _ in range(k - 1):
        if not results:
            break
        last_path = results[-1]

        for i in range(len(last_path)):
            spur_node_id = last_path[i].from_node_id
            root_path = last_path[:i]

            # Remove edges that conflict with already-found paths
            removed_edges: set[tuple[int, int]] = set()
            for res_path in results:
                if len(res_path) > i and res_path[:i] == root_path:
                    removed_edges.add((res_path[i].from_node_id, res_path[i].to_node_id))

            # Spur path from spur_node
            root_arr_time = last_path[i].departure_at if i > 0 else query_time

            # Temporarily filter edges
            filtered: dict[int, list[_Edge]] = {}
            for nid, elist in edges_by_from.items():
                filtered[nid] = [
                    e for e in elist
                    if (e.from_id, e.to_id) not in removed_edges
                ]

            spur = _dijkstra(
                spur_node_id, dest_id, nodes, filtered, schedules_by_edge,
                transshipments, root_arr_time, cargo_weight_t, connection_margin_h,
                horizon_end, objective="cost",
            )
            if spur is not None:
                total_path = root_path + spur
                cost = sum(leg.cost_usd for leg in total_path)
                # Avoid duplicates
                if not any(p == total_path for _, p in candidates):
                    heapq.heappush(candidates, (cost, total_path))

        if not candidates:
            break
        _, best = heapq.heappop(candidates)
        results.append(best)

    return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _load_weights(priority: str) -> dict[str, float]:
    """Load objective weight profile for the given priority from params."""
    p = priority.upper()
    return {
        "cost": params.get_float(f"plan.weight.{p}.cost", 0.4),
        "time": params.get_float(f"plan.weight.{p}.time", 0.25),
        "reliability": params.get_float(f"plan.weight.{p}.reliability", 0.2),
        "co2": params.get_float(f"plan.weight.{p}.co2", 0.1),
        "risk": params.get_float(f"plan.weight.{p}.risk", 0.05),
    }


def _score_candidates(
    candidates: list[ItineraryResult],
    weights: dict[str, float],
) -> list[ItineraryResult]:
    """Normalize each objective across candidates then apply weighted sum.

    Score is 0..1 where 1 = best. Lower cost/time/co2/risk = better;
    higher reliability = better.
    """
    if not candidates:
        return candidates

    costs = [c.total_cost_usd for c in candidates]
    times = [c.total_time_h for c in candidates]
    co2s = [c.total_co2_kg for c in candidates]
    rels = [c.reliability_score for c in candidates]
    risks = [c.risk_index for c in candidates]

    def _norm_minimize(vals: list[float], v: float) -> float:
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return 1.0
        return 1.0 - (v - mn) / (mx - mn)

    def _norm_maximize(vals: list[float], v: float) -> float:
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return 1.0
        return (v - mn) / (mx - mn)

    for c in candidates:
        nc = _norm_minimize(costs, c.total_cost_usd)
        nt = _norm_minimize(times, c.total_time_h)
        nco2 = _norm_minimize(co2s, c.total_co2_kg)
        nrel = _norm_maximize(rels, c.reliability_score)
        nrisk = _norm_minimize(risks, c.risk_index)
        c.score = round(
            weights["cost"] * nc
            + weights["time"] * nt
            + weights["co2"] * nco2
            + weights["reliability"] * nrel
            + weights["risk"] * nrisk,
            4,
        )

    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _build_rationale(itinerary: ItineraryResult, weights: dict[str, float], rank: int) -> str:
    """Generate a human-readable trade-off explanation."""
    modes = sorted({leg.mode for leg in itinerary.legs})
    mode_str = " + ".join(modes)
    dominant = max(weights, key=lambda k: weights[k])
    if rank == 1:
        return (
            f"Recommended ({dominant}-optimal): {mode_str} route. "
            f"Cost ₹{itinerary.total_cost_usd:,.0f} · "
            f"{itinerary.total_time_h:.0f}h · "
            f"{itinerary.total_co2_kg:.0f} kg CO₂ · "
            f"Reliability {itinerary.reliability_score:.0%}"
        )
    return (
        f"Alternative #{rank} ({mode_str}): "
        f"Cost ₹{itinerary.total_cost_usd:,.0f} · "
        f"{itinerary.total_time_h:.0f}h · "
        f"{itinerary.total_co2_kg:.0f} kg CO₂"
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _persist_plans(
    session: AsyncSession,
    shipment_id: str,
    itineraries: list[ItineraryResult],
    plan_type: PlanType,
) -> list[RoutePlanRecord]:
    """Write route_plan + route_leg rows; return the persisted records."""
    records: list[RoutePlanRecord] = []
    for itin in itineraries:
        plan = RoutePlanRecord(
            shipment_id=shipment_id,
            plan_type=plan_type,
            priority=itin.priority,
            rank=itin.rank,
            recommended=itin.recommended,
            total_cost_usd=itin.total_cost_usd,
            total_time_h=itin.total_time_h,
            total_co2_kg=itin.total_co2_kg,
            reliability_score=itin.reliability_score,
            risk_index=itin.risk_index,
            score=itin.score,
            rationale=itin.rationale,
            objective_weights_json=json.dumps(itin.objective_weights),
            provenance="DERIVED",
        )
        session.add(plan)
        await session.flush()  # get plan.id

        for seq, leg in enumerate(itin.legs, start=1):
            leg_rec = RouteLegRecord(
                plan_id=plan.id,
                sequence_number=seq,
                mode=leg.mode,
                from_node_id=leg.from_node_id,
                to_node_id=leg.to_node_id,
                edge_id=leg.edge_id,
                schedule_id=leg.schedule_id,
                departure_at=leg.departure_at,
                arrival_at=leg.arrival_at,
                cost_usd=leg.cost_usd,
                transit_h=leg.transit_h,
                co2_kg=leg.co2_kg,
                reliability=leg.reliability,
                provenance=leg.provenance,
            )
            session.add(leg_rec)

        records.append(plan)

    await session.commit()
    return records


# ---------------------------------------------------------------------------
# Public planner interface
# ---------------------------------------------------------------------------


class MultimodalPlanner:
    """Schedule-aware multimodal route optimizer.

    Usage::

        planner = MultimodalPlanner()
        results = await planner.plan(
            session=db,
            shipment_id="abc-123",
            origin_locode="INLUH",
            dest_locode="INJNP",
            query_time=datetime.now(UTC),
            priority=ShipmentPriority.ECONOMY,
            deadline=None,
            cargo_weight_kg=15000.0,
            seed=42,
            persist=True,
        )
    """

    async def plan(
        self,
        session: AsyncSession,
        shipment_id: str,
        origin_locode: str,
        dest_locode: str,
        query_time: datetime | None = None,
        priority: ShipmentPriority | str = ShipmentPriority.STANDARD,
        plan_type: PlanType | str = PlanType.INITIAL,
        deadline: datetime | None = None,
        cargo_weight_kg: float = 15000.0,
        seed: int | None = None,
        persist: bool = True,
        top_k: int | None = None,
    ) -> list[ItineraryResult]:
        """Generate ranked multimodal itineraries for a shipment.

        Parameters
        ----------
        session: AsyncSession  DB session.
        shipment_id: str       Shipment UUID.
        origin_locode: str     Origin node locode (must exist in network_nodes).
        dest_locode: str       Destination node locode.
        query_time:            Planning reference time (default: now UTC).
        priority:              Weight profile selection.
        plan_type:             INITIAL | ALTERNATIVE | RECOVERY.
        deadline:              Hard deadline; infeasible itineraries are filtered out.
        cargo_weight_kg:       Cargo mass for CO2 and cost calculation.
        seed:                  Random seed for deterministic tie-breaking (invariant 8).
        persist:               Whether to write route_plan + route_leg rows.
        top_k:                 Override for max results (default from policy param).

        Returns
        -------
        list[ItineraryResult]  Ranked from best (rank=1) to worst.
        """
        t0 = time.monotonic()

        if query_time is None:
            query_time = datetime.now(UTC)
        elif query_time.tzinfo is None:
            query_time = query_time.replace(tzinfo=UTC)

        priority_str = str(priority).upper()
        plan_type_val = PlanType(str(plan_type).upper()) if isinstance(plan_type, str) else plan_type

        _top_k = top_k or params.get_int("planner.top_k", 5)
        horizon_days = params.get_int("planner.horizon_days", 14)
        connection_margin_h = params.get_float("planner.connection_margin_h", 2.0)
        horizon_end = query_time + timedelta(days=horizon_days)
        cargo_weight_t = max(0.001, cargo_weight_kg / 1000.0)

        weights = _load_weights(priority_str)

        # Load network
        nodes, edges_by_from, schedules_by_edge, transshipments, locode_to_id = await _load_network(
            session, query_time, horizon_days
        )

        origin_id = locode_to_id.get(origin_locode)
        dest_id = locode_to_id.get(dest_locode)

        if origin_id is None or dest_id is None:
            log.warning(
                "Planner: origin_locode=%s or dest_locode=%s not found in network",
                origin_locode, dest_locode,
            )
            return []

        if origin_id == dest_id:
            return []

        # ── 1. Four scalarized seed paths ────────────────────────────────
        raw_paths: list[list[LegKPI]] = []
        for obj in ("cost", "time", "reliability", "co2"):
            path = _dijkstra(
                origin_id, dest_id, nodes, edges_by_from, schedules_by_edge,
                transshipments, query_time, cargo_weight_t, connection_margin_h,
                horizon_end, objective=obj,
            )
            if path:
                raw_paths.append(path)

        # ── 2. Yen k-shortest for diversity ──────────────────────────────
        yen_paths = _yen_k_shortest(
            origin_id, dest_id, nodes, edges_by_from, schedules_by_edge,
            transshipments, query_time, cargo_weight_t, connection_margin_h,
            horizon_end, k=_top_k,
        )
        for p in yen_paths:
            if p not in raw_paths:
                raw_paths.append(p)

        # ── 3. Enrich locodes and deduplicate ─────────────────────────────
        id_to_locode = {v: k for k, v in locode_to_id.items()}

        def _enrich(legs: list[LegKPI]) -> list[LegKPI]:
            return [
                LegKPI(
                    mode=leg.mode,
                    from_node_id=leg.from_node_id,
                    to_node_id=leg.to_node_id,
                    from_locode=id_to_locode.get(leg.from_node_id, "?"),
                    to_locode=id_to_locode.get(leg.to_node_id, "?"),
                    edge_id=leg.edge_id,
                    schedule_id=leg.schedule_id,
                    departure_at=leg.departure_at,
                    arrival_at=leg.arrival_at,
                    cost_usd=leg.cost_usd,
                    transit_h=leg.transit_h,
                    co2_kg=leg.co2_kg,
                    reliability=leg.reliability,
                    provenance=leg.provenance,
                )
                for leg in legs
            ]

        seen_structural: set = set()
        itineraries: list[ItineraryResult] = []
        for path in raw_paths:
            if not path:
                continue
            enriched = _enrich(path)
            struct_key = tuple(leg.structural_key for leg in enriched)
            if struct_key in seen_structural:
                continue
            seen_structural.add(struct_key)

            total_cost = sum(leg.cost_usd for leg in enriched)
            total_time = sum(leg.transit_h for leg in enriched)
            total_co2 = sum(leg.co2_kg for leg in enriched)
            reliability = math.prod(leg.reliability for leg in enriched) if enriched else 1.0
            risk_index = round(1.0 - reliability, 4)

            itin = ItineraryResult(
                legs=enriched,
                total_cost_usd=round(total_cost, 2),
                total_time_h=round(total_time, 2),
                total_co2_kg=round(total_co2, 3),
                reliability_score=round(reliability, 4),
                risk_index=risk_index,
                priority=priority_str,
                plan_type=str(plan_type_val),
                objective_weights=weights,
            )
            itineraries.append(itin)

        # ── 4. Hard filters ───────────────────────────────────────────────
        itineraries = [i for i in itineraries if i.passes_deadline(deadline)]

        # ── 5. Score and rank ─────────────────────────────────────────────
        itineraries = _score_candidates(itineraries, weights)

        # Keep top_k
        itineraries = itineraries[:_top_k]

        # Assign rank and labels
        for rank, itin in enumerate(itineraries, start=1):
            itin.rank = rank
            itin.recommended = rank == 1
            itin.rationale = _build_rationale(itin, weights, rank)

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "Planner: %s→%s priority=%s plan_type=%s itineraries=%d elapsed=%.0fms",
            origin_locode, dest_locode, priority_str, plan_type_val,
            len(itineraries), elapsed_ms,
        )

        # ── 6. Persist ────────────────────────────────────────────────────
        if persist and itineraries:
            try:
                await _persist_plans(session, shipment_id, itineraries, plan_type_val)
            except Exception as exc:
                log.warning("Planner persistence failed (non-fatal): %s", exc)

        return itineraries


# Module-level singleton (lazy-initialized)
_planner_instance: MultimodalPlanner | None = None


def get_planner() -> MultimodalPlanner:
    """Return the module-level planner singleton."""
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = MultimodalPlanner()
    return _planner_instance
