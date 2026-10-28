"""DataCo corridor replay: real demand weighting -> DERIVED intl shipments.

ORDER FACTS are real (revenue, scheduled-vs-real days -> SLA outcome, region demand);
the ROUTE is the planner's recommendation (DERIVED); nothing claims live positions.
Idempotent by DC-<Order Id> citation. Deterministic under --seed.
"""
import argparse
import asyncio
import importlib.util
import logging
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select

# Set up paths and import models/enums
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexafreight.adapters.routing._geometry import haversine_km
from nexafreight.services.consolidation import containers_for_total
from nexafreight.enums import CargoClass, LegStatus, OrderSlaStatus, Provenance, ShipmentStatus, TransportMode
from nexafreight.models.leg import Leg
from nexafreight.models.location import Location
from nexafreight.models.network import NetworkNode, NetworkEdge
from nexafreight.models.order import Order
from nexafreight.models.shipment import Shipment
from nexafreight.services.demo_parties import assign_parties, load_party_pools
from nexafreight.services.planner import get_planner
from nexafreight.core.clock import world_now
from nexafreight.database import get_session_factory

# Load script 21
spec = importlib.util.spec_from_file_location("drip_orders", str(Path(__file__).parent / "21_drip_orders.py"))
drip_orders = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drip_orders)
_leg_geometry = drip_orders.WorldDripper._leg_geometry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("replay_dataco")

CORRIDORS = [
    ("USNYC", "NLRTM", set(), {"Northern Europe", "Western Europe", "Southern Europe"}),
    ("CNSHA", "USLAX", set(), {"Western US", "Eastern US", "Canada", "West of USA", "East of USA", "US Center", "South of  USA"}),
    ("SGSIN", "JPTYO", set(), {"Eastern Asia"}),
    ("INJNP", "SGSIN", set(), {"Southeast Asia"}),
    ("INJNP", "INTKG", set(), {"South Asia"}),
    ("AEBUE", "ZADUR", set(), {"Africa", "West Africa", "North Africa", "East Africa", "Central Africa", "Southern Africa"}),
    ("BRSSZ", "ZADUR", set(), {"South America", "Central America", "Caribbean"}),
    ("SGSIN", "AUSYD", set(), {"Oceania"}),
    ("DEHAM", "NLRTM", set(), {"Eastern Europe"}),
]

USECOLS = [
    "Order Id", "Order Region", "Order Item Total", "Shipping Mode",
    "Days for shipment (scheduled)", "Days for shipping (real)", "order date (DateOrders)"
]

def load_orders_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1", usecols=USECOLS)
    df = df.dropna(subset=["Order Id", "Order Region"])
    df = df.drop_duplicates(subset=["Order Id"])
    df["order date (DateOrders)"] = pd.to_datetime(df["order date (DateOrders)"], errors="coerce")
    df = df.dropna(subset=["order date (DateOrders)"])
    return df

def assign_corridors(df: pd.DataFrame) -> tuple[dict[tuple[str, str], list[int]], list[int]]:
    lanes = { (c[0], c[1]): [] for c in CORRIDORS }
    unmapped = []
    
    regions = df["Order Region"].values
    for idx, region in enumerate(regions):
        mapped = False
        for origin, dest, _orig_regions, dest_regions in CORRIDORS:
            if region in dest_regions:
                lanes[(origin, dest)].append(idx)
                mapped = True
                break
        if not mapped:
            unmapped.append(idx)
            
    return lanes, unmapped

async def run(args):
    df = load_orders_frame(args.dataco)
    lanes, unmapped = assign_corridors(df)
    
    total_mapped = sum(len(v) for _, v in lanes.items())
    corridors_count = len([v for _, v in lanes.items() if v])
    print(f"REPORT > REPLAY: CSV unique orders={len(df)}, mapped={total_mapped} ({len(unmapped)} regions unmapped), corridors={corridors_count}")
    
    # Sort lanes by demand (descending length)
    top_lanes = sorted(lanes.items(), key=lambda item: len(item[1]), reverse=True)[:args.top]
    
    if args.dry_run:
        for (o, d), idxs in top_lanes:
            print(f"  {o}->{d}: {len(idxs)} orders")
        return
        
    rng = random.Random(args.seed)
    planner = get_planner()
    world = world_now()
    
    SessionLocal = get_session_factory()
    
    async with SessionLocal() as session:
        # Load caches
        loc_rows = (await session.execute(select(Location))).scalars().all()
        locode_to_location = {loc.locode: loc.id for loc in loc_rows}
        nodes = (await session.execute(select(NetworkNode))).scalars().all()
        node_coords = {n.locode: (n.latitude, n.longitude) for n in nodes}
        edge_geometry = {
            e.id: e.geometry_json
            for e in (await session.execute(select(NetworkEdge))).scalars().all()
            if e.geometry_json
        }
        party_pools = await load_party_pools(session)
        
        # Select existing citations to skip
        existing = set((await session.execute(
            select(Order.order_number).where(Order.order_number.like("DC-%"))
        )).scalars().all())
        
        shipments_created = 0
        delivered = 0
        in_transit = 0
        skipped = 0
        
        live_mix = getattr(args, "live_mix", False)
        in_transit_ratio = getattr(args, "in_transit_ratio", 0.45)
        delayed_ratio = getattr(args, "delayed_ratio", 0.15)
        delivered_ratio = getattr(args, "delivered_ratio", 0.25)

        count = 0
        delayed_count = 0
        for (o, d), idxs in top_lanes:
            if count >= args.limit:
                break
            
            for i in idxs:
                if count >= args.limit:
                    break
                    
                row = df.iloc[i]
                order_id = str(int(row["Order Id"]))
                citation = f"DC-{order_id}"
                
                if citation in existing:
                    continue
                    
                scheduled = int(row["Days for shipment (scheduled)"])
                real = int(row["Days for shipping (real)"])
                
                target_mode = "DEFAULT"
                if live_mix:
                    r = rng.random()
                    if r < in_transit_ratio:
                        target_mode = "IN_TRANSIT"
                    elif r < in_transit_ratio + delayed_ratio:
                        target_mode = "DELAYED"
                    elif r < in_transit_ratio + delayed_ratio + delivered_ratio:
                        target_mode = "DELIVERED"
                    else:
                        target_mode = "PLANNED"

                order_date = world - timedelta(days=rng.randint(1, args.days_back))
                deadline = order_date + timedelta(days=scheduled)
                sla_status = OrderSlaStatus.ON_TIME if real <= scheduled else OrderSlaStatus.LATE
                route_deadline = order_date + timedelta(days=max(scheduled, 45))
                
                revenue = float(row["Order Item Total"])
                shipping_cost = revenue * rng.uniform(0.08, 0.25)
                weight = rng.uniform(8000, 18000)
                volume = rng.uniform(20, 55)
                
                shipment_id = str(uuid.uuid4())
                order = Order(
                    order_number=citation,
                    shipment_id=shipment_id,
                    order_date=order_date,
                    sla_deadline=deadline,
                    revenue=round(revenue, 2),
                    shipping_cost=round(shipping_cost, 2),
                    sla_status=sla_status,
                    cargo_class=CargoClass.STANDARD,
                    weight_kg=round(weight, 1),
                    volume_m3=round(volume, 2),
                    shipping_mode=TransportMode.SEA,
                )
                assign_parties(order, party_pools, rng)
                
                shipment = Shipment(
                    id=shipment_id,
                    provenance=Provenance.DERIVED,
                    status=ShipmentStatus.PLANNED,
                    container_count=containers_for_total(order.weight_kg, order.volume_m3, "SEA"),
                    route_version=1,
                    origin_id=locode_to_location.get(o),
                    destination_id=locode_to_location.get(d),
                    cargo_class=CargoClass.STANDARD,
                    primary_transport_mode=TransportMode.SEA,
                    strictest_sla_deadline=deadline,
                    planned_departure=order_date + timedelta(days=1),
                )
                
                session.add_all([order, shipment])
                await session.flush()
                
                # Try planning
                itins = await planner.plan(session, shipment_id, o, d, query_time=order_date, deadline=route_deadline, persist=True)
                if not itins:
                    await session.rollback()
                    # retry ONCE with persist=False
                    itins = await planner.plan(session, shipment_id, o, d, query_time=order_date, deadline=route_deadline, persist=False)
                    if not itins:
                        await session.rollback()
                        log.warning(f"no itinerary for {citation} {o}->{d} - skipped")
                        skipped += 1
                        continue
                
                itin = itins[0]
                legs = []

                # Compute time offset if live_mix is requested
                offset = timedelta(0)
                if live_mix and itin.legs:
                    itin_start = itin.legs[0].departure_at
                    itin_end = itin.legs[-1].arrival_at
                    itin_dur = itin_end - itin_start
                    dur_s = max(3600.0, itin_dur.total_seconds())

                    if target_mode in ("IN_TRANSIT", "DELAYED"):
                        progress = rng.uniform(0.18, 0.78)
                        journey_start = world - timedelta(seconds=dur_s * progress)
                        offset = journey_start - itin_start
                    elif target_mode == "DELIVERED":
                        days_ago = timedelta(days=rng.uniform(1.0, float(args.days_back)))
                        journey_end = world - days_ago
                        offset = journey_end - itin_end
                    elif target_mode == "PLANNED":
                        days_ahead = timedelta(days=rng.uniform(0.5, 4.0))
                        journey_start = world + days_ahead
                        offset = journey_start - itin_start

                for seq, kpi in enumerate(itin.legs, start=1):
                    o_coord = node_coords.get(kpi.from_locode)
                    d_coord = node_coords.get(kpi.to_locode)
                    km = haversine_km(*o_coord, *d_coord) if o_coord and d_coord else None
                    
                    leg_dep = kpi.departure_at + offset
                    leg_arr = kpi.arrival_at + offset

                    if world >= leg_arr:
                        status = LegStatus.COMPLETED
                        act_dep = leg_dep
                        act_arr = leg_arr
                    elif world >= leg_dep:
                        status = LegStatus.IN_PROGRESS
                        act_dep = leg_dep
                        act_arr = None
                    else:
                        status = LegStatus.PLANNED
                        act_dep = None
                        act_arr = None
                        
                    geom = _leg_geometry(TransportMode(kpi.mode), o_coord, d_coord, edge_geometry.get(kpi.edge_id))
                    
                    leg = Leg(
                        shipment_id=shipment_id,
                        sequence_number=seq,
                        transport_mode=TransportMode(kpi.mode),
                        status=status,
                        origin_id=locode_to_location.get(kpi.from_locode),
                        destination_id=locode_to_location.get(kpi.to_locode),
                        planned_departure=leg_dep,
                        planned_arrival=leg_arr,
                        actual_departure=act_dep,
                        actual_arrival=act_arr,
                        route_geometry_json=geom,
                        distance_km=round(km, 1) if km else None,
                        co2_kg=round(kpi.co2_kg, 1),
                        provenance=Provenance.DERIVED,
                        route_version=1,
                    )
                    session.add(leg)
                    legs.append(leg)
                
                if not legs:
                    await session.rollback()
                    skipped += 1
                    continue
                    
                shipment.primary_transport_mode = TransportMode(itin.legs[0].mode)
                order.shipping_mode = TransportMode(itin.legs[0].mode)
                shipment.planned_departure = legs[0].planned_departure

                if target_mode == "DELAYED":
                    shipment.status = ShipmentStatus.DELAYED
                    delayed_count += 1
                    order.sla_status = OrderSlaStatus.LATE
                    order.sla_deadline = legs[-1].planned_arrival - timedelta(hours=rng.randint(6, 36))
                elif all(leg.status == LegStatus.COMPLETED for leg in legs):
                    shipment.status = ShipmentStatus.DELIVERED
                    delivered += 1
                    for leg in legs:
                        leg.actual_departure = leg.planned_departure
                        leg.actual_arrival = leg.planned_arrival
                elif any(leg.status == LegStatus.IN_PROGRESS for leg in legs):
                    shipment.status = ShipmentStatus.IN_TRANSIT
                    in_transit += 1
                else:
                    shipment.status = ShipmentStatus.PLANNED
                    
                await session.flush()

                # Seed immediate position report for in-progress legs
                for leg in legs:
                    if leg.status == LegStatus.IN_PROGRESS and leg.route_geometry_json:
                        try:
                            from nexafreight.workers.position_interpolator import _LegData, _interpolate_linear
                            from nexafreight.models.position_report import PositionReport
                            leg_dto = _LegData(
                                leg_id=leg.id,
                                mode=leg.transport_mode.value if hasattr(leg.transport_mode, "value") else str(leg.transport_mode),
                                route_geometry=leg.route_geometry_json,
                                planned_departure=leg.planned_departure,
                                planned_arrival=leg.planned_arrival,
                                actual_departure=leg.actual_departure,
                            )
                            pos = _interpolate_linear(leg_dto, world, leg.route_geometry_json)
                            if pos:
                                report = PositionReport(
                                    leg_id=leg.id,
                                    asset_type=pos.asset_type.value if hasattr(pos.asset_type, "value") else str(pos.asset_type),
                                    latitude=pos.lat,
                                    longitude=pos.lon,
                                    speed_knots=pos.speed_knots,
                                    heading=pos.heading_deg,
                                    reported_at=world,
                                    provenance=pos.provenance.value if hasattr(pos.provenance, "value") else str(pos.provenance),
                                )
                                session.add(report)
                        except Exception as e:
                            log.debug("Skip initial position seed for leg %s: %s", leg.id, e)

                await session.commit()
                shipments_created += 1
                count += 1
                
        print(f"REPORT > REPLAY DONE: shipments={shipments_created} (in_transit={in_transit}, delayed={delayed_count}, delivered={delivered}), skipped={skipped}, provenance=DERIVED, citations=DC-<Order Id>")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataco", type=Path, default=Path("data/raw/dataco/DataCoSupplyChain.csv"))
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--days-back", type=int, default=21)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live-mix", action="store_true", help="Distribute shipments across in_transit, delayed, delivered, planned")
    ap.add_argument("--in-transit-ratio", type=float, default=0.45)
    ap.add_argument("--delayed-ratio", type=float, default=0.15)
    ap.add_argument("--delivered-ratio", type=float, default=0.25)
    ap.add_argument("--db-url", type=str, default=None)
    args = ap.parse_args()
    asyncio.run(run(args))
