"""Task 18: parties — seeding idempotency, deterministic assignment, detail API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from nexafreight.enums import CargoClass, PartyRole, TransportMode
from nexafreight.models import Order, Party
from nexafreight.services.demo_parties import assign_parties, load_party_pools, seed_parties


async def _make_party(session, name: str, role: PartyRole) -> Party:
    party = Party(name=name, role=role, city="X")
    session.add(party)
    await session.flush()
    return party


async def test_seed_parties_idempotent_nine_actors(db_session) -> None:
    """The factory defines 9 parties; seeding twice never duplicates."""
    created = await seed_parties(db_session)
    assert created == 9
    again = await seed_parties(db_session)
    assert again == 0
    rows = (await db_session.execute(select(Party))).scalars().all()
    assert len(rows) == 9
    roles = {str(r.role).split(".")[-1] for r in rows}
    assert roles == {"SHIPPER", "CONSIGNEE", "CARRIER"}


async def test_assign_parties_deterministic_under_seeded_rng(db_session) -> None:
    """Same seed -> same triple; empty pool -> None."""
    s1 = await _make_party(db_session, "S1", PartyRole.SHIPPER)
    s2 = await _make_party(db_session, "S2", PartyRole.SHIPPER)
    c1 = await _make_party(db_session, "C1", PartyRole.CONSIGNEE)
    t1 = await _make_party(db_session, "T1", PartyRole.CARRIER)
    pools = await load_party_pools(db_session)
    assert pools["SHIPPER"] and pools["CONSIGNEE"] and pools["CARRIER"]

    def build(i: int) -> Order:
        return Order(order_number=f"ORD-P{i}", sla_deadline=datetime.now(UTC) + timedelta(days=5))

    import random

    a, b = build(1), build(2)
    ra, rb = random.Random(42), random.Random(42)
    assign_parties(a, pools, ra)
    assign_parties(b, pools, rb)
    assert (a.shipper_id, a.consignee_id, a.carrier_id) == (b.shipper_id, b.consignee_id, b.carrier_id)
    assert {a.shipper_id, b.shipper_id} <= {s1.id, s2.id}
    assert a.consignee_id == c1.id and a.carrier_id == t1.id

    empty: dict[str, list[int]] = {"SHIPPER": [], "CONSIGNEE": [], "CARRIER": []}
    orphan = build(3)
    assign_parties(orphan, empty, random.Random(1))
    assert orphan.shipper_id is None and orphan.carrier_id is None


async def test_shipment_detail_surfaces_party_names(
    db_session,
    make_shipment,
    make_order,
    make_location,
    client,
    auth_headers_factory,
    seed_admin_user,
) -> None:
    origin = await make_location(locode="INJNP", name="JNPT", country_code="IN", latitude=18.95, longitude=72.95)
    dest = await make_location(locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.92, longitude=4.479)
    shipment = await make_shipment(origin=origin, destination=dest, status="PLANNED", route_version=1)

    shipper = await _make_party(db_session, "Deccan Textiles Ltd", PartyRole.SHIPPER)
    consignee = await _make_party(db_session, "Atlas Home NL BV", PartyRole.CONSIGNEE)
    carrier = await _make_party(db_session, "Monsoon Maritime Lines", PartyRole.CARRIER)

    order = await make_order(
        order_number="ORD-PARTY-2",
        shipment=shipment,
        revenue=50_000.0,
        shipping_cost=5_000.0,
        sla_deadline=datetime.now(UTC) + timedelta(days=10),
        shipping_mode=TransportMode.SEA,
        cargo_class=CargoClass.STANDARD,
    )
    order.shipper_id = shipper.id
    order.consignee_id = consignee.id
    order.carrier_id = carrier.id
    await db_session.commit()

    headers = auth_headers_factory(seed_admin_user)
    response = await client.get(f"/api/shipments/{shipment.id}", headers=headers)
    assert response.status_code == 200
    orders = response.json().get("orders", [])
    assert orders, "detail must include orders"
    assert orders[0]["shipper"] == "Deccan Textiles Ltd"
    assert orders[0]["consignee"] == "Atlas Home NL BV"
    assert orders[0]["carrier"] == "Monsoon Maritime Lines"
