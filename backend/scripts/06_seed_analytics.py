#!/usr/bin/env python3
import asyncio
import random
import uuid
import sys
import os
from sqlalchemy import text

# Add src to python path so it can be run directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from datetime import datetime, timedelta, UTC

from nexafreight.database import get_session_factory
from nexafreight.models.location import Location
from nexafreight.models.shipment import Shipment
from nexafreight.models.order import Order
from nexafreight.enums import ShipmentStatus, TransportMode, CargoClass, OrderSlaStatus, Provenance

async def main():
    async with get_session_factory()() as session:
        # Get some locations
        res = await session.execute(text("SELECT id FROM locations LIMIT 10"))
        loc_ids = [r[0] for r in res.fetchall()]
        if len(loc_ids) < 2:
            print("Not enough locations to seed analytics.")
            return

        print("Seeding 100 historical shipments for analytics...")
        
        now = datetime.now(UTC)
        for _ in range(100):
            orig = random.choice(loc_ids)
            dest = random.choice(loc_ids)
            while dest == orig:
                dest = random.choice(loc_ids)
                
            mode = random.choice([TransportMode.SEA, TransportMode.AIR, TransportMode.ROAD])
            
            # create shipment
            s = Shipment(
                id=str(uuid.uuid4()),
                provenance=Provenance.HISTORICAL,
                origin_id=orig,
                destination_id=dest,
                primary_transport_mode=mode,
                cargo_class=CargoClass.STANDARD,
                container_count=random.randint(1, 10),
                status=ShipmentStatus.DELIVERED,
                planned_departure=now - timedelta(days=random.randint(30, 100)),
                strictest_sla_deadline=now - timedelta(days=random.randint(10, 30))
            )
            
            # create orders
            num_orders = random.randint(1, 3)
            orders = []
            for i in range(num_orders):
                revenue = random.uniform(20000, 100000)
                cost = revenue * random.uniform(0.5, 0.8)
                
                o = Order(
                    order_number=f"ORD-HIST-{uuid.uuid4().hex[:8].upper()}",
                    shipment=s,
                    order_date=s.planned_departure - timedelta(days=random.randint(1, 5)),
                    sla_deadline=s.strictest_sla_deadline,
                    revenue=revenue,
                    shipping_cost=cost,
                    sla_status=OrderSlaStatus.ON_TIME,
                    shipping_mode=mode,
                    cargo_class=CargoClass.STANDARD,
                )
                orders.append(o)
                
            session.add(s)
            session.add_all(orders)
            
        await session.commit()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
