"""Regression tests for E25 + E26 (found live in the demo world, task 10).

Both defects sat in check_port_congestion — code that could never execute on
main because the ports table was always empty:
  E25: port.locode lazy-loads Port.location -> MissingGreenlet under asyncio.
  E26: order.sla_deadline (naive from SQLite) vs aware planned_arrival
       -> TypeError.
Together they made the congestion scan crash on its first real run.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import LegStatus, LocationType, ShipmentStatus, TransportMode
from nexafreight.models.leg import Leg
from nexafreight.models.location import Location
from nexafreight.models.order import Order
from nexafreight.models.port import Port, PortDailyStat
from nexafreight.models.shipment import Shipment
from nexafreight.workers.disruption_detector import check_shipments

NOW = datetime.now(UTC)


@pytest.mark.asyncio
async def test_congestion_scan_survives_real_ports_and_fires(db_session: AsyncSession):
    """Port + 90d stats + IN_PROGRESS leg into the spiked port -> 1 alert."""
    # location + port (E25 needs the relationship path exercised)
    loc = Location(
        locode="TSTPRT",
        name="Test Port",
        country_code="IN",
        location_type=LocationType.PORT,
        latitude=18.95,
        longitude=72.95,
    )
    db_session.add(loc)
    await db_session.flush()
    port = Port(location_id=loc.id)
    db_session.add(port)
    await db_session.flush()

    # 10 days of flat baseline, then a 2.0x spike today (above warn 1.5)
    d = (NOW - timedelta(days=10)).date()
    while d < NOW.date():
        db_session.add(PortDailyStat(port_id=port.id, stat_date=d, congestion_index=0.70))
        d = date.fromordinal(d.toordinal() + 1)
    db_session.add(
        PortDailyStat(port_id=port.id, stat_date=NOW.date(), congestion_index=1.40)
    )

    # shipment with an ACTIVE leg INTO the port + one order (E26 path)
    dest = Location(
        locode="TSTHUB",
        name="Test Hub",
        country_code="IN",
        location_type=LocationType.INLAND_DEPOT,
        latitude=19.10,
        longitude=73.00,
    )
    db_session.add(dest)
    await db_session.flush()
    shipment = Shipment(
        provenance="SIMULATED",
        status=ShipmentStatus.IN_TRANSIT,
        primary_transport_mode=TransportMode.SEA,
        cargo_class="STANDARD",
        container_count=1,
        route_version=1,
        planned_departure=NOW - timedelta(days=2),
        strictest_sla_deadline=NOW + timedelta(days=10),
        origin_id=dest.id,  # any valid FK
        destination_id=loc.id,
    )
    db_session.add(shipment)
    await db_session.flush()
    leg = Leg(
        shipment_id=shipment.id,
        sequence_number=1,
        route_version=1,
        transport_mode=TransportMode.SEA,
        status=LegStatus.IN_PROGRESS,
        origin_id=dest.id,
        destination_id=loc.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=2),
        provenance="SIMULATED",
    )
    order = Order(
        order_number="ORD-E25-REG",
        shipment_id=shipment.id,
        order_date=NOW - timedelta(days=3),
        sla_deadline=NOW + timedelta(days=10),
        revenue=50000.0,
        shipping_cost=5000.0,
        shipping_mode=TransportMode.SEA,
        cargo_class="STANDARD",
    )
    db_session.add_all([leg, order])
    await db_session.commit()

    summary = await check_shipments(db_session, now=NOW)
    assert summary["congestion_candidates"] == 1, "spiked port must flag its inbound leg"
    assert summary["created"] == 1, "candidate must become a Disruption + Alert"
