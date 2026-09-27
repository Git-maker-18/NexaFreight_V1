"""Unit tests for order-to-shipment consolidation engine (T-017).

Tests the real src/nexafreight/services/consolidation.py implementation
using in-memory SQLite and fixture-created Order rows only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import CargoClass, OrderSlaStatus, TransportMode
from nexafreight.models import Order, Shipment
from nexafreight.services.consolidation import OrderView, consolidate_orders


def _week_of(dt: datetime) -> int:
    """ISO calendar week for a datetime (matches implementation's grouping)."""
    return dt.isocalendar()[1]


@pytest.mark.asyncio
async def test_correct_grouping_key(db_session: AsyncSession) -> None:
    """Orders sharing origin/dest/mode/cargo/week group into one shipment."""
    # Two orders, identical dimensions, same week
    base_time = datetime(2024, 1, 3, tzinfo=UTC)  # Wednesday, week 1
    o1 = Order(
        order_number="ORD-G1-A",
        sla_deadline=base_time + timedelta(days=20),
        revenue=1000.0,
        shipping_cost=100.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
    )
    o2 = Order(
        order_number="ORD-G1-B",
        sla_deadline=base_time + timedelta(days=25),
        revenue=2000.0,
        shipping_cost=200.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
    )
    # Different dimension (different cargo_class) -> must NOT join above group
    o3 = Order(
        order_number="ORD-OTHER",
        sla_deadline=base_time + timedelta(days=22),
        revenue=1500.0,
        shipping_cost=150.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.REFRIGERATED,  # differs
        origin_id=1,
        destination_id=2,
    )
    db_session.add_all([o1, o2, o3])
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    # Should create exactly 2 shipments: one for (STANDARD group), one for REFRIGERATED
    assert len(shipments) == 2

    # Verify grouping: find shipment containing o1 and o2
    result = await db_session.execute(select(Shipment))
    shipments_in_db = result.scalars().all()
    assert len(shipments_in_db) == 2

    # Reload orders to get updated shipment_id
    await db_session.refresh(o1)
    await db_session.refresh(o2)
    await db_session.refresh(o3)

    assert o1.shipment_id is not None
    assert o1.shipment_id == o2.shipment_id  # grouped together
    assert o3.shipment_id != o1.shipment_id  # different group


@pytest.mark.asyncio
async def test_week_boundary_correctness(db_session: AsyncSession) -> None:
    """Orders in different ISO weeks are NOT grouped together."""
    # Same origin/dest/mode/cargo, but different weeks
    week1_time = datetime(2024, 1, 3, tzinfo=UTC)  # Week 1
    week2_time = datetime(2024, 1, 10, tzinfo=UTC)  # Week 2

    o1 = Order(
        order_number="ORD-W1",
        sla_deadline=week1_time + timedelta(days=20),
        revenue=1000.0,
        shipping_cost=100.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.AIR,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
        created_at=week1_time,
    )
    o2 = Order(
        order_number="ORD-W2",
        sla_deadline=week2_time + timedelta(days=20),
        revenue=1000.0,
        shipping_cost=100.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.AIR,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
        created_at=week2_time,
    )
    db_session.add_all([o1, o2])
    await db_session.commit()

    await consolidate_orders(db_session)

    await db_session.refresh(o1)
    await db_session.refresh(o2)

    assert o1.shipment_id != o2.shipment_id, "Different weeks must not group"


@pytest.mark.asyncio
async def test_strictest_sla_computation(db_session: AsyncSession) -> None:
    """Shipment's strictest_sla_deadline = earliest deadline among grouped orders."""
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    deadlines = [
        base_time + timedelta(days=30),  # latest
        base_time + timedelta(days=10),  # EARLIEST (strictest)
        base_time + timedelta(days=20),
    ]
    orders = []
    for i, deadline in enumerate(deadlines):
        o = Order(
            order_number=f"ORD-SLA-{i}",
            sla_deadline=deadline,
            revenue=1000.0,
            shipping_cost=100.0,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=TransportMode.SEA,
            cargo_class=CargoClass.STANDARD,
            origin_id=1,
            destination_id=2,
            created_at=base_time,
        )
        orders.append(o)
        db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment.strictest_sla_deadline == deadlines[1], "Must be earliest deadline"


@pytest.mark.asyncio
async def test_capacity_limit_splits_shipments(db_session: AsyncSession) -> None:
    """Exceeding container capacity splits into multiple shipments."""
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    # 25 unmeasured STANDARD orders: nominal 5,000 kg / 6 m3 each -> 5 fit
    # in one SEA container (25 t / 30 m3); the 6th would exceed 28 t.
    for i in range(25):
        o = Order(
            order_number=f"ORD-CAP-{i}",
            sla_deadline=base_time + timedelta(days=30),
            revenue=1000.0,
            shipping_cost=100.0,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=TransportMode.SEA,
            cargo_class=CargoClass.STANDARD,
            origin_id=1,
            destination_id=2,
            created_at=base_time,
        )
        db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    # Capacity binds before the legacy 20-order cap: 25 / 5 = 5 shipments
    assert len(shipments) == 5
    counts = [s.container_count for s in shipments]
    assert all(c == 1 for c in counts), "Each 25 t chunk fits one container"


@pytest.mark.asyncio
async def test_container_count_correctness(db_session: AsyncSession) -> None:
    """Container count follows the capacity math (E13), not order count.

    5 orders x (5,000 kg, 5 m3) = 25 t / 25 m3 — one SEA container holds
    all five (28 t / 33 m3), where the old count math demanded five.
    """
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    for i in range(5):
        o = Order(
            order_number=f"ORD-CT-{i}",
            sla_deadline=base_time + timedelta(days=30),
            revenue=1000.0,
            shipping_cost=100.0,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=TransportMode.SEA,
            cargo_class=CargoClass.STANDARD,
            origin_id=1,
            destination_id=2,
            created_at=base_time,
            weight_kg=5_000.0,
            volume_m3=5.0,
        )
        db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    assert len(shipments) == 1
    assert shipments[0].container_count == 1


@pytest.mark.asyncio
async def test_oversized_order_gets_multiple_containers(db_session: AsyncSession) -> None:
    """E13 acceptance: container counts respect tonnage (90 t -> 4 SEA boxes)."""
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    o = Order(
        order_number="ORD-HEAVY",
        sla_deadline=base_time + timedelta(days=30),
        revenue=9000.0,
        shipping_cost=900.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
        created_at=base_time,
        weight_kg=90_000.0,
        volume_m3=10.0,
    )
    db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    assert len(shipments) == 1
    assert shipments[0].container_count == 4  # ceil(90_000 / 28_000)


@pytest.mark.asyncio
async def test_container_count_respects_tonnage() -> None:
    """A single 90 t order needs 4 SEA containers (E13 acceptance)."""
    from nexafreight.services.consolidation import containers_for_total

    assert containers_for_total(90_000.0, 1.0, "SEA") == 4
    assert containers_for_total(27_000.0, 1.0, "SEA") == 1
    assert containers_for_total(1.0, 66.0, "SEA") == 2  # cube-bound
    # Unknown mode falls back to the SEA (default) capacity.
    assert containers_for_total(30_000.0, 0.0, "PIPELINE") == 2


@pytest.mark.asyncio
async def test_capacity_chunking_splits_heavy_group() -> None:
    """Groups split on capacity, not only the 20-order cap (E13)."""
    from nexafreight.services.consolidation import ShipmentSpec, _consolidate_orders_sync

    base = datetime(2024, 1, 3, tzinfo=UTC)
    orders = [
        OrderView(
            id=i,
            order_number=f"ORD-HV-{i}",
            origin_country_code="US",
            dest_country_code="NL",
            shipping_mode="SEA",
            cargo_class="STANDARD",
            order_date=base,
            sla_deadline=base + timedelta(days=10),
            revenue=1_000.0,
            shipping_cost=100.0,
            weight_kg=10_000.0,  # 10 t each: only 2 fit a 28 t container
            volume_m3=1.0,
        )
        for i in range(25)
    ]

    specs = _consolidate_orders_sync(orders, {}, default_origin_id=1, default_dest_id=2)

    # 2 orders per shipment (20 t <= 28 t; 30 t would exceed) -> 13 chunks
    assert len(specs) == 13
    assert all(len(s.order_ids) <= 2 for s in specs)
    # Each 20 t chunk fits one container
    assert all(s.container_count == 1 for s in specs)


@pytest.mark.asyncio
async def test_nominal_fallback_when_unmeasured() -> None:
    """Orders without measurements use cargo-class nominals (documented)."""
    from nexafreight.services.consolidation import (
        NOMINAL_ORDER_LOAD,
        ShipmentSpec,
        _consolidate_orders_sync,
        effective_load,
    )

    assert effective_load(None, None, "REFRIGERATED") == NOMINAL_ORDER_LOAD["REFRIGERATED"]
    assert effective_load(1_000.0, None, "HAZMAT")[0] == 1_000.0  # measurement wins

    base = datetime(2024, 1, 3, tzinfo=UTC)
    one = OrderView(
        id=1,
        order_number="ORD-NOM-1",
        origin_country_code="US",
        dest_country_code="NL",
        shipping_mode="SEA",
        cargo_class="REFRIGERATED",
        order_date=base,
        sla_deadline=base + timedelta(days=10),
        revenue=1_000.0,
        shipping_cost=100.0,
        weight_kg=None,
        volume_m3=None,
    )
    specs = _consolidate_orders_sync([one], {}, default_origin_id=1, default_dest_id=2)
    assert len(specs) == 1
    assert specs[0].container_count == 1  # 8 t / 14 m3 fits one container


@pytest.mark.asyncio
async def test_single_order_group(db_session: AsyncSession) -> None:
    """A single order still produces a valid shipment."""
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    o = Order(
        order_number="ORD-SINGLE",
        sla_deadline=base_time + timedelta(days=30),
        revenue=5000.0,
        shipping_cost=500.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.ROAD,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
        created_at=base_time,
    )
    db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    assert len(shipments) == 1
    assert shipments[0].container_count == 1
    await db_session.refresh(o)
    assert o.shipment_id == shipments[0].id


@pytest.mark.asyncio
async def test_order_to_shipment_linkage(db_session: AsyncSession) -> None:
    """Every consolidated Order.shipment_id points to the resulting Shipment."""
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    orders = []
    for i in range(3):
        o = Order(
            order_number=f"ORD-LNK-{i}",
            sla_deadline=base_time + timedelta(days=30),
            revenue=1000.0,
            shipping_cost=100.0,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=TransportMode.SEA,
            cargo_class=CargoClass.STANDARD,
            origin_id=1,
            destination_id=2,
            created_at=base_time,
        )
        orders.append(o)
        db_session.add(o)
    await db_session.commit()

    shipments = await consolidate_orders(db_session)

    assert len(shipments) == 1
    shipment = shipments[0]
    for o in orders:
        await db_session.refresh(o)
        assert o.shipment_id == shipment.id, f"Order {o.order_number} not linked"


@pytest.mark.asyncio
async def test_empty_input(db_session: AsyncSession) -> None:
    """Consolidating zero orders produces zero shipments, no error."""
    shipments = await consolidate_orders(db_session)
    assert shipments == []


@pytest.mark.asyncio
async def test_idempotency_skipped(db_session: AsyncSession) -> None:
    """Idempotency not applicable — consolidation is a one-time batch process.

    Re-running consolidation on already-consolidated orders would create
    duplicate shipments (Orders already have shipment_id set). This test
    documents that behavior rather than asserting incorrect idempotency.
    """
    base_time = datetime(2024, 1, 3, tzinfo=UTC)
    o = Order(
        order_number="ORD-IDEM",
        sla_deadline=base_time + timedelta(days=30),
        revenue=1000.0,
        shipping_cost=100.0,
        sla_status=OrderSlaStatus.ON_TIME,
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.STANDARD,
        origin_id=1,
        destination_id=2,
        created_at=base_time,
    )
    db_session.add(o)
    await db_session.commit()

    # First run
    shipments_1 = await consolidate_orders(db_session)
    assert len(shipments_1) == 1

    # Second run: order already has shipment_id, so it is skipped by the
    # implementation (WHERE shipment_id IS NULL). No new shipment created.
    shipments_2 = await consolidate_orders(db_session)
    assert len(shipments_2) == 0, "Already-consolidated orders must not create new shipments"
