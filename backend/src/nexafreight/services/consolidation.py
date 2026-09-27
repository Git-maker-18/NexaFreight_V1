"""Shipment consolidation service.

Groups line-level / order-level records into containerized multi-modal shipments.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import CargoClass, LocationType, Provenance, ShipmentStatus, TransportMode
from nexafreight.models.location import Location
from nexafreight.models.order import Order
from nexafreight.models.shipment import Shipment


@dataclass
class OrderView:
    id: int
    order_number: str
    origin_country_code: str
    dest_country_code: str
    shipping_mode: str
    cargo_class: str
    order_date: datetime
    sla_deadline: datetime
    revenue: float
    shipping_cost: float
    historical_late_delivery: bool = False
    real_shipping_days: float = 0.0
    weight_kg: float | None = None
    volume_m3: float | None = None


@dataclass
class ShipmentSpec:
    id: str  # UUID string
    origin_id: int
    destination_id: int
    primary_transport_mode: str
    cargo_class: str
    container_count: int
    planned_departure: datetime
    strictest_sla_deadline: datetime
    order_ids: list[int] = field(default_factory=list)
    total_revenue: float = 0.0


# --- Task 21 (E13): capacity-aware container math ---------------------------
# Per-container/trip capacities as (payload_kg, volume_m3). SEA is grounded
# in the published ISO 668 20' GP spec: 30,480 kg max gross − ~2,300 kg tare
# => ~28,000 kg payload, 33.2 m3 internal (rounded down). Other modes are
# documented planning nominals (747F-class freighter; legal articulated
# truck; block-train wagon group) — kept round, they only bound grouping.
CONTAINER_CAPACITY: dict[str, tuple[float, float]] = {
    "SEA": (28_000.0, 33.0),
    "AIR": (100_000.0, 500.0),
    "ROAD": (25_000.0, 90.0),
    "RAIL": (60_000.0, 150.0),
}
DEFAULT_CAPACITY = CONTAINER_CAPACITY["SEA"]

# Conservative per-order nominals used ONLY when an order carries no
# measured weight/volume (DataCo-era rows lack measurements). These are
# planning figures, not observations — the dripper writes measured values
# for demo-world orders, so the fallback only covers legacy rows.
NOMINAL_ORDER_LOAD: dict[str, tuple[float, float]] = {
    "STANDARD": (5_000.0, 6.0),
    "REFRIGERATED": (8_000.0, 14.0),
    "HAZMAT": (5_000.0, 10.0),
    "HIGH_VALUE": (4_000.0, 8.0),
}
DEFAULT_NOMINAL = NOMINAL_ORDER_LOAD["STANDARD"]


def enum_key(value: str | None) -> str:
    """'TransportMode.SEA' / 'sea' / None -> 'SEA' / 'SEA' / ''."""
    return str(value or "").upper().split(".")[-1]


def effective_load(
    weight_kg: float | None, volume_m3: float | None, cargo_class: str | None
) -> tuple[float, float]:
    """Resolve an order's (kg, m3): measurements win, cargo-class nominal otherwise."""
    nom_w, nom_v = NOMINAL_ORDER_LOAD.get(enum_key(cargo_class), DEFAULT_NOMINAL)
    return (
        max(float(weight_kg), 0.0) if weight_kg is not None else nom_w,
        max(float(volume_m3), 0.0) if volume_m3 is not None else nom_v,
    )


def containers_for_total(weight_kg: float, volume_m3: float, mode: str | None) -> int:
    """Containers needed for a total load: binding dimension wins, min 1.

    This is the E13 fix — counts come from tonnage/cube, not order counts.
    """
    cap_w, cap_v = CONTAINER_CAPACITY.get(enum_key(mode), DEFAULT_CAPACITY)
    by_w = math.ceil(weight_kg / cap_w) if weight_kg > 0 else 1
    by_v = math.ceil(volume_m3 / cap_v) if volume_m3 > 0 else 1
    return max(1, by_w, by_v)


def _split_group(orders, mode_key: str, max_orders_per_shipment: int, load_of):
    """Split one consolidation group into shipment chunks under BOTH caps:
    order count (legacy behaviour) and container capacity (Task 21). A
    single oversized order gets its own chunk; containers_for_total then
    prices the extra containers."""
    cap_w, cap_v = CONTAINER_CAPACITY.get(mode_key, DEFAULT_CAPACITY)
    chunk: list = []
    chunk_w = chunk_v = 0.0
    for order in orders:
        w, v = load_of(order)
        if chunk and (
            len(chunk) >= max_orders_per_shipment
            or chunk_w + w > cap_w + 1e-9
            or chunk_v + v > cap_v + 1e-9
        ):
            yield chunk, chunk_w, chunk_v
            chunk, chunk_w, chunk_v = [], 0.0, 0.0
        chunk.append(order)
        chunk_w += w
        chunk_v += v
    if chunk:
        yield chunk, chunk_w, chunk_v


def _consolidate_orders_sync(
    orders: Sequence[OrderView],
    country_to_location: dict[str, int],
    default_origin_id: int,
    default_dest_id: int,
    max_orders_per_shipment: int = 20,
) -> list[ShipmentSpec]:
    groups: dict[tuple[str, str, str, str, int, int], list[OrderView]] = defaultdict(list)

    for order in orders:
        orig_cc = order.origin_country_code.upper() if order.origin_country_code else "US"
        dest_cc = order.dest_country_code.upper() if order.dest_country_code else "US"
        mode = order.shipping_mode.upper() if order.shipping_mode else "SEA"
        cargo = order.cargo_class.upper() if order.cargo_class else "STANDARD"

        d = order.order_date or order.sla_deadline
        year, week, _ = d.isocalendar()

        key = (orig_cc, dest_cc, mode, cargo, year, week)
        groups[key].append(order)

    shipments: list[ShipmentSpec] = []

    for (orig_cc, dest_cc, mode, cargo, _year, _week), group_orders in groups.items():
        mode_key = enum_key(mode)
        for chunk, tot_w, tot_v in _split_group(
            group_orders,
            mode_key,
            max_orders_per_shipment,
            lambda o: effective_load(o.weight_kg, o.volume_m3, o.cargo_class),
        ):
            strictest_deadline = min(o.sla_deadline for o in chunk)
            earliest_departure = min(o.order_date for o in chunk)
            tot_rev = sum(o.revenue for o in chunk)

            orig_id = country_to_location.get(orig_cc, default_origin_id)
            dest_id = country_to_location.get(dest_cc, default_dest_id)
            if orig_id == dest_id:
                dest_id = default_dest_id if orig_id != default_dest_id else default_origin_id

            shipment_id = str(uuid.uuid4())
            shipments.append(
                ShipmentSpec(
                    id=shipment_id,
                    origin_id=orig_id,
                    destination_id=dest_id,
                    primary_transport_mode=mode,
                    cargo_class=cargo,
                    container_count=containers_for_total(tot_w, tot_v, mode_key),
                    planned_departure=earliest_departure,
                    strictest_sla_deadline=strictest_deadline,
                    order_ids=[o.id for o in chunk],
                    total_revenue=round(tot_rev, 2),
                )
            )

    return shipments


async def _ensure_locations_exist(session: AsyncSession, location_ids: set[int]) -> None:
    for loc_id in location_ids:
        loc = await session.get(Location, loc_id)
        if loc is None:
            loc = Location(
                id=loc_id,
                locode=f"L{loc_id:04d}",
                name=f"Location {loc_id}",
                country_code="US",
                location_type=LocationType.PORT,
                latitude=0.0,
                longitude=0.0,
            )
            session.add(loc)
    await session.flush()


def _normalize_dt(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _consolidate_orders_async(
    session: AsyncSession,
    max_orders_per_shipment: int = 20,
) -> list[Shipment]:
    result = await session.execute(select(Order).where(Order.shipment_id.is_(None)))
    orders = list(result.scalars().all())
    if not orders:
        return []

    needed_loc_ids: set[int] = set()
    groups: dict[tuple[int, int, Any, Any, int, int], list[Order]] = defaultdict(list)
    for order in orders:
        orig_id = getattr(order, "origin_id", 1) or 1
        dest_id = getattr(order, "destination_id", 2) or 2
        needed_loc_ids.add(orig_id)
        needed_loc_ids.add(dest_id)
        mode = order.shipping_mode
        cargo = order.cargo_class
        dt = _normalize_dt(order.created_at if order.created_at is not None else order.sla_deadline)
        year, week, _ = dt.isocalendar()
        key = (orig_id, dest_id, mode, cargo, year, week)
        groups[key].append(order)

    await _ensure_locations_exist(session, needed_loc_ids)

    created_shipments: list[Shipment] = []
    for (orig_id, dest_id, mode, cargo, _year, _week), group_orders in groups.items():
        mode_key = enum_key(mode)
        for chunk, tot_w, tot_v in _split_group(
            group_orders,
            mode_key,
            max_orders_per_shipment,
            lambda o: effective_load(o.weight_kg, o.volume_m3, o.cargo_class),
        ):
            strictest = min(_normalize_dt(o.sla_deadline) for o in chunk)

            transport_mode = TransportMode(mode) if isinstance(mode, str) else mode
            cargo_class_val = CargoClass(cargo) if isinstance(cargo, str) else cargo

            shipment = Shipment(
                provenance=Provenance.DERIVED,
                origin_id=orig_id,
                destination_id=dest_id,
                primary_transport_mode=transport_mode,
                cargo_class=cargo_class_val,
                status=ShipmentStatus.PLANNED,
                container_count=containers_for_total(tot_w, tot_v, mode_key),
                strictest_sla_deadline=strictest,
                route_version=1,
            )
            session.add(shipment)
            await session.flush()

            for order in chunk:
                order.shipment_id = shipment.id

            created_shipments.append(shipment)

    await session.commit()
    for s in created_shipments:
        await session.refresh(s)
        if s.strictest_sla_deadline and s.strictest_sla_deadline.tzinfo is None:
            s.strictest_sla_deadline = s.strictest_sla_deadline.replace(tzinfo=UTC)

    return created_shipments


def consolidate_orders(
    orders_or_session: Any,
    country_to_location: dict[str, int] | None = None,
    default_origin_id: int = 1,
    default_dest_id: int = 2,
    max_orders_per_shipment: int = 20,
) -> Any:
    """Consolidate orders into containerized shipments.

    Supports:
    - AsyncSession: await consolidate_orders(session) -> list[Shipment]
    - Sequence[OrderView]: consolidate_orders(order_views, ...) -> list[ShipmentSpec]
    """
    if isinstance(orders_or_session, AsyncSession):
        return _consolidate_orders_async(orders_or_session, max_orders_per_shipment)
    return _consolidate_orders_sync(
        orders_or_session,
        country_to_location or {},
        default_origin_id,
        default_dest_id,
        max_orders_per_shipment,
    )
