#!/usr/bin/env python3
"""
21_drip_orders.py
=================
Task 6 (Time-World) — makes the demo world breathe: drips orders day by day,
plans each through the system's own multimodal planner, and materializes the
recommended itinerary into execution-layer Leg rows.

Design (from the validated Simulation A):
  - ~8 orders per weekday (weekday-only cadence; weekends quiet)
  - a --backfill tail (~2-3 weeks of prior days, lightly sampled) so the
    world boots ALIVE: delivered shipments, in-flight containers, upcoming
    deadlines — instead of an empty map
  - deterministic under --seed (seeded RNG; same world every rebuild)
  - idempotent per world-day via the time_world.last_drip_date parameter
  - provenance discipline: Orders/Shipments/Legs = SIMULATED; the plans the
    planner persists stay DERIVED (they derive from the network data)

All "now" decisions go through core.clock.world_now() — the Time-World seam.
With warp=1.0 (default) the world is honest real time and every existing
worker (interpolator, SLA checker, disruption detector, SSE map) just works.

Run:
    python scripts/21_drip_orders.py --once          # drip today (cron-able)
    python scripts/21_drip_orders.py --backfill 14   # seed 14 prior days too
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from nexafreight.config import get_settings  # noqa: E402
from nexafreight.core import params  # noqa: E402
from nexafreight.core.clock import world_now  # noqa: E402
from nexafreight.database import get_session_factory  # noqa: E402
from nexafreight.adapters.routing._geometry import haversine_km  # noqa: E402
from nexafreight.enums import (  # noqa: E402
    CargoClass,
    LegStatus,
    OrderSlaStatus,
    Provenance,
    ShipmentStatus,
    TransportMode,
)
from nexafreight.models.leg import Leg  # noqa: E402
from nexafreight.models.location import Location  # noqa: E402
from nexafreight.models.network import NetworkNode  # noqa: E402
from nexafreight.models.order import Order  # noqa: E402
from nexafreight.services.demo_parties import assign_parties, load_party_pools  # noqa: E402
from nexafreight.services.consolidation import (  # noqa: E402
    DEFAULT_NOMINAL,
    NOMINAL_ORDER_LOAD,
    containers_for_total,
    enum_key,
)
from nexafreight.adapters.routing import great_circle_geojson_str  # noqa: E402
from nexafreight.models import NetworkEdge  # noqa: E402
from nexafreight.adapters.routing.sea_route import compute_sea_route  # noqa: E402
from nexafreight.models.parameter import ParameterEmpirical  # noqa: E402
from nexafreight.models.shipment import Shipment  # noqa: E402
from nexafreight.services.planner import get_planner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("drip_orders")

LAST_DRIP_KEY = "time_world.last_drip_date"


class WorldDripper:
    def __init__(self, per_day: int, seed: int | None, min_lane_km: float = 300.0):
        self.per_day = per_day
        self.rng = random.Random(seed)
        self.min_lane_km = min_lane_km
        self.locode_to_location: dict[str, int] = {}
        self.node_coords: dict[str, tuple[float, float]] = {}
        self.in_nodes: list[str] = []

    async def _load_caches(self, session) -> None:
        loc_rows = (await session.execute(select(Location))).scalars().all()
        self.locode_to_location = {loc.locode: loc.id for loc in loc_rows}
        nodes = (await session.execute(select(NetworkNode))).scalars().all()
        self.node_coords = {n.locode: (n.latitude, n.longitude) for n in nodes}
        self.in_nodes = sorted(n.locode for n in nodes if n.locode.startswith("IN"))
        if len(self.in_nodes) < 2:
            raise SystemExit("Need >=2 IN* network nodes (run alembic upgrade head)")
        self.party_pools = await load_party_pools(session)
        # Day-14: cached edge geometry (network_edges.geometry_json)
        self.edge_geometry = {
            e.id: e.geometry_json
            for e in (await session.execute(select(NetworkEdge))).scalars().all()
            if e.geometry_json
        }


        # Network nodes may carry planning codes absent from the UN/LOCODE
        # ingest (e.g. INJPR). Upsert the missing ones as locations so the
        # execution layer (shipments.origin_id/destination_id) resolves.
        # (Location has no ProvenanceMixin yet — hygiene task 22; the demo
        # world's provenance is carried by Shipment/Order/Leg.)
        created = 0
        for n in nodes:
            if n.locode in self.locode_to_location:
                continue
            loc = Location(
                locode=n.locode,
                name=n.name,
                country_code=n.locode[:2],
                location_type=self._location_type(n.node_type),
                latitude=n.latitude,
                longitude=n.longitude,
            )
            session.add(loc)
            await session.flush()
            self.locode_to_location[n.locode] = loc.id
            created += 1
        if created:
            await session.commit()
            log.info("Created %d SIMULATED locations for network-only nodes", created)

    @staticmethod
    def _location_type(node_type: str):
        from nexafreight.enums import LocationType

        mapping = {
            "PORT": LocationType.PORT,
            "AIRPORT": LocationType.AIRPORT,
            "ICD": LocationType.INLAND_DEPOT,
            "RAIL_TERMINAL": LocationType.INLAND_DEPOT,
            "RIVER_TERMINAL": LocationType.INLAND_DEPOT,
            "ROAD_HUB": LocationType.INLAND_DEPOT,
        }
        return mapping.get(str(node_type).split(".")[-1], LocationType.INLAND_DEPOT)

    def _pick_lane(self) -> tuple[str, str, float]:
        """Origin/dest pair with a minimum great-circle distance (real lanes)."""
        for _ in range(50):
            o, d = self.rng.sample(self.in_nodes, 2)
            km = haversine_km(*self.node_coords[o], *self.node_coords[d])
            if km >= self.min_lane_km:
                return o, d, km
        return o, d, km  # last attempt wins (near-degenerate networks)

    def _world_day(self, world: datetime, days_back: int) -> datetime:
        day = world - timedelta(days=days_back)
        # weekday cadence (Simulation A: weekday 100%) — skip Sat/Sun
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day

    def _leg_status_for(self, dep: datetime, arr: datetime, world: datetime) -> LegStatus:
        if world >= arr:
            return LegStatus.COMPLETED
        if world >= dep:
            return LegStatus.IN_PROGRESS
        return LegStatus.PLANNED

    @staticmethod
    def _densified_line(o_coord: tuple[float, float], d_coord: tuple[float, float], points: int = 16) -> str:
        """Densified great-circle LineString as GeoJSON (lon,lat pairs).

        The interpolator walks this geometry to place moving markers. The
        straight great-circle is an honest SIMULATED approximation; coastal
        sea lanes will be upgraded to searoute geometry as polish later.
        """
        lat1, lon1 = radians(o_coord[0]), radians(o_coord[1])
        lat2, lon2 = radians(d_coord[0]), radians(d_coord[1])
        coords: list[list[float]] = []
        for i in range(points + 1):
            f = i / points
            d = 2 * asin(
                sqrt(
                    sin((lat2 - lat1) / 2) ** 2
                    + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
                )
            )
            if d < 1e-12:
                coords.append([o_coord[1], o_coord[0]])
                continue
            a = sin((1 - f) * d) / sin(d)
            b = sin(f * d) / sin(d)
            x = a * cos(lat1) * cos(lon1) + b * cos(lat2) * cos(lon2)
            y = a * cos(lat1) * sin(lon1) + b * cos(lat2) * sin(lon2)
            z = a * sin(lat1) + b * sin(lat2)
            lat = degrees(atan2(z, sqrt(x * x + y * y)))
            lon = degrees(atan2(y, x))
            coords.append([round(lon, 5), round(lat, 5)])
        import json as _json

        return _json.dumps({"type": "LineString", "coordinates": coords})

    @staticmethod
    def _leg_geometry(
        mode: TransportMode,
        o_coord: tuple[float, float] | None,
        d_coord: tuple[float, float] | None,
        edge_geometry_json: str | None = None,
    ) -> str | None:
        """Geometry the position interpolator walks (day-12d upgrade).

        SEA follows REAL marine-lane geometry from the searoute graph — the
        same adapter that measures the VIA_CAPE corridor factors and the
        Red Sea drill — so ships visibly sail around land, not through it.
        AIR gets a great-circle arc (what aircraft actually fly). ROAD/RAIL
        keep the densified straight approximation until an OSM/ORS
        path-geometry pass (the documented v2 upgrade). Any adapter failure
        degrades to the straight line: geometry is presentation, the drip
        must never break on it.
        """
        # Day-14: cached edge geometry (scripts/25, real ORS road paths)
        # wins over every fallback -- compute once per edge, reuse forever.
        if edge_geometry_json:
            return edge_geometry_json
        if o_coord is None or d_coord is None:
            # Coordinates unknown (stale node cache): leave geometry empty —
            # the interpolator skips legs without geometry (endpoint fallback).
            return None
        try:
            if mode == TransportMode.SEA:
                route = compute_sea_route(
                    o_coord[0],
                    o_coord[1],
                    d_coord[0],
                    d_coord[1],
                    vessel_class="neo-panamax",
                )
                if route.geometry_geojson:
                    return route.geometry_geojson
            elif mode == TransportMode.AIR:
                return great_circle_geojson_str(o_coord[0], o_coord[1], d_coord[0], d_coord[1])
        except Exception as exc:  # deliberate: presentation fallback only
            log.warning(
                "leg geometry fell back to straight line (%s: %s)", type(exc).__name__, exc
            )
        return WorldDripper._densified_line(o_coord, d_coord)

    def _shipment_state(self, legs: list[Leg], world: datetime) -> ShipmentStatus:
        if all(leg.status == LegStatus.COMPLETED for leg in legs):
            return ShipmentStatus.DELIVERED
        if any(leg.status == LegStatus.IN_PROGRESS for leg in legs):
            return ShipmentStatus.IN_TRANSIT
        if all(leg.status == LegStatus.PLANNED for leg in legs):
            return ShipmentStatus.PLANNED
        return ShipmentStatus.IN_TRANSIT

    async def _materialize_legs(self, session, shipment_id: str, itin, world: datetime) -> list[Leg]:
        """Itinerary (planning layer) -> Leg rows (execution layer)."""
        legs: list[Leg] = []
        for seq, kpi in enumerate(itin.legs, start=1):
            o_id = self.locode_to_location.get(kpi.from_locode)
            d_id = self.locode_to_location.get(kpi.to_locode)
            if o_id is None or d_id is None:
                log.warning("locode %s/%s missing from locations — skipping leg", kpi.from_locode, kpi.to_locode)
                continue
            o_coord = self.node_coords.get(kpi.from_locode)
            d_coord = self.node_coords.get(kpi.to_locode)
            km = haversine_km(*o_coord, *d_coord) if o_coord and d_coord else None
            leg = Leg(
                shipment_id=shipment_id,
                sequence_number=seq,
                route_version=1,
                transport_mode=TransportMode(kpi.mode),
                status=self._leg_status_for(kpi.departure_at, kpi.arrival_at, world),
                origin_id=o_id,
                destination_id=d_id,
                planned_departure=kpi.departure_at,
                planned_arrival=kpi.arrival_at,
                # Task-7 wire: the position interpolator walks this geometry
                # to place moving markers (LINESTRING GeoJSON, lon/lat).
                # Day-12d: SEA = real searoute marine lanes, AIR = great
                # circle, ROAD/RAIL = densified straight (documented).
                route_geometry_json=self._leg_geometry(
                    TransportMode(kpi.mode), o_coord, d_coord,
                    self.edge_geometry.get(kpi.edge_id),
                ),
                distance_km=round(km, 1) if km else None,
                co2_kg=round(kpi.co2_kg, 1),
                provenance=Provenance.SIMULATED,
            )
            session.add(leg)
            legs.append(leg)
        return legs

    async def _drip_one(self, session, planner, world: datetime, order_day: datetime, seq: int) -> Shipment:
        o_locode, d_locode, _km = self._pick_lane()
        shipment_id = str(uuid.uuid4())

        order_date = order_day + timedelta(hours=self.rng.uniform(8, 18))
        window_days = self.rng.randint(6, 25)
        deadline = order_date + timedelta(days=window_days)
        revenue = round(self.rng.uniform(20_000, 100_000), 2)
        shipping_cost = round(revenue * self.rng.uniform(0.08, 0.25), 2)

        order_number = f"ORD-W{order_day.strftime('%Y%m%d')}-{seq:03d}"
        order = Order(
            order_number=order_number,
            shipment_id=shipment_id,
            order_date=order_date,
            sla_deadline=deadline,
            revenue=revenue,
            shipping_cost=shipping_cost,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=TransportMode.ROAD,  # provisional; set from the plan
            cargo_class=self.rng.choice(list(CargoClass)),
        )
        # Task 21 (E13): demo orders carry a measured load (cargo-class
        # nominal +/-30%), and the shipment's container count derives from
        # it — no more coin-flip containers.
        nom_w, nom_v = NOMINAL_ORDER_LOAD.get(enum_key(order.cargo_class), DEFAULT_NOMINAL)
        order.weight_kg = round(nom_w * self.rng.uniform(0.7, 1.3), 1)
        order.volume_m3 = round(nom_v * self.rng.uniform(0.7, 1.3), 2)
        # Task 18: deterministic party assignment (shipper/consignee/carrier).
        assign_parties(order, self.party_pools, self.rng)

        shipment = Shipment(
            id=shipment_id,
            provenance=Provenance.SIMULATED,
            status=ShipmentStatus.PLANNED,
            container_count=containers_for_total(order.weight_kg or 0.0, order.volume_m3 or 0.0, "ROAD"),
            route_version=1,
            # NOT NULL columns; provisional until the planner picks the chain
            # (overwritten below once the recommended itinerary is known).
            primary_transport_mode=TransportMode.ROAD,
            cargo_class=order.cargo_class,
            planned_departure=order_date + timedelta(days=1),
            strictest_sla_deadline=deadline,
        )
        # Location ids (origin/destination) resolved after planning; planner
        # works on network locodes. Use the resolved hub locations:
        shipment.origin_id = self.locode_to_location[o_locode]
        shipment.destination_id = self.locode_to_location[d_locode]
        session.add_all([shipment, order])
        await session.flush()

        itineraries = await planner.plan(
            session,
            shipment_id,
            o_locode,
            d_locode,
            # Planning happens when the ORDER is placed — backfilled orders
            # then get legs in their own past (delivered/in-flight history),
            # not a world where every container departs at boot time.
            query_time=order_date,
            deadline=deadline,
            persist=True,
        )
        if not itineraries:
            await session.rollback()
            log.warning("no itinerary for %s->%s (%s) — skipped", o_locode, d_locode, order_number)
            raise ValueError("no itinerary")

        legs = await self._materialize_legs(session, shipment_id, itineraries[0], world)
        if legs:
            modes = [str(leg.transport_mode) for leg in legs]
            shipment.primary_transport_mode = TransportMode(modes[0])
            order.shipping_mode = TransportMode(modes[0])
        shipment.strictest_sla_deadline = deadline
        shipment.status = self._shipment_state(legs, world)
        if shipment.status == ShipmentStatus.DELIVERED:
            for leg in legs:
                if leg.status == LegStatus.COMPLETED:
                    leg.actual_departure = leg.planned_departure
                    leg.actual_arrival = leg.planned_arrival
        return shipment

    async def drip_day(self, session, planner, world: datetime, days_back: int) -> int:
        order_day = self._world_day(world, days_back)
        # orders already exist for that world-day (idempotency by number prefix)
        prefix = f"ORD-W{order_day.strftime('%Y%m%d')}-%"
        existing = (
            await session.execute(select(func.count()).select_from(Order).where(Order.order_number.like(prefix)))
        ).scalar_one()
        if existing:
            log.info("world-day %s already dripped (%d orders) — skipped", order_day.date(), existing)
            return 0

        created = 0
        for seq in range(1, self.per_day + 1):
            try:
                await self._drip_one(session, planner, world, order_day, seq)
                created += 1
            except ValueError:
                continue
        await session.commit()
        log.info("world-day %s: dripped %d orders", order_day.date(), created)
        return created


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="drip the current world-day and exit")
    ap.add_argument("--backfill", type=int, default=0, help="also seed N prior world-days (business days)")
    ap.add_argument("--per-day", type=int, default=8, help="orders per weekday (Simulation A: 8)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for determinism")
    ap.add_argument("--loop-every-min", type=float, default=0.0, help=">0: keep running, drip every N minutes")
    args = ap.parse_args()

    get_settings()
    dripper = WorldDripper(per_day=args.per_day, seed=args.seed)

    async with get_session_factory()() as session:
        await dripper._load_caches(session)

    planner = get_planner()
    world = world_now()
    log.info("world_now=%s (warp=%s)", world.isoformat(), params.get_float("time_world.warp", 1.0))

    total = 0
    async with get_session_factory()() as session:
        for back in range(args.backfill, 0, -1):
            total += await dripper.drip_day(session, planner, world, days_back=back)
        if args.once or args.backfill == 0:
            total += await dripper.drip_day(session, planner, world, days_back=0)
        # record last drip (world-date) for idempotency visibility
        await session.merge(
            ParameterEmpirical(
                key=LAST_DRIP_KEY,
                value=world.date().isoformat(),
                unit="date",
                source="TIME_WORLD",
                as_of=datetime.now(UTC),
                derivation_method="21_drip_orders: last world-day dripped",
            )
        )
        await session.commit()

    counts = await _world_summary()
    log.info("=" * 54)
    log.info("Drip complete: %d new orders", total)
    log.info("World totals: %s", counts)
    log.info("=" * 54)

    if args.loop_every_min > 0:
        import asyncio as _a

        while True:
            await _a.sleep(args.loop_every_min * 60)
            async with get_session_factory()() as session:
                total += await dripper.drip_day(session, planner, world_now(), days_back=0)
            log.info("loop drip: +%d (total %d)", total, total)
    return 0


async def _world_summary() -> str:
    async with get_session_factory()() as session:
        n_ship = (await session.execute(select(func.count()).select_from(Shipment))).scalar_one()
        n_legs = (await session.execute(select(func.count()).select_from(Leg))).scalar_one()
        in_transit = (
            await session.execute(
                select(func.count()).select_from(Shipment).where(Shipment.status == ShipmentStatus.IN_TRANSIT)
            )
        ).scalar_one()
        delivered = (
            await session.execute(
                select(func.count()).select_from(Shipment).where(Shipment.status == ShipmentStatus.DELIVERED)
            )
        ).scalar_one()
    return f"shipments={n_ship} (in_transit={in_transit}, delivered={delivered}), legs={n_legs}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
