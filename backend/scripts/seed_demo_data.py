"""Seed realistic demo data for NexaFreight Control Tower.

Populates ports, vessels, shipments, multi-modal legs with GeoJSON geometry,
orders, live position reports, and a sample disruption/alert.

Usage:
    python scripts/seed_demo_data.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.auth import hash_password
from nexafreight.config import get_settings
from nexafreight.database import get_session_factory
from nexafreight.enums import (
    AlertSeverity,
    AlertStatus,
    CargoClass,
    DisruptionStatus,
    DisruptionType,
    LegStatus,
    LocationType,
    OrderSlaStatus,
    Provenance,
    ShipmentStatus,
    TransportMode,
    UserRole,
)
from nexafreight.models.alert import Alert
from nexafreight.models.disruption import Disruption
from nexafreight.models.leg import Leg
from nexafreight.models.location import Location
from nexafreight.models.order import Order, OrderItem
from nexafreight.models.port import Port, PortDailyStat
from nexafreight.models.position import PositionReport
from nexafreight.models.shipment import Shipment
from nexafreight.models.user import User
from nexafreight.models.vessel import Vessel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_demo_data")


async def seed_all(session: AsyncSession) -> None:
    settings = get_settings()
    now = datetime.now(UTC)

    # -------------------------------------------------------------------------
    # 1. Users
    # -------------------------------------------------------------------------
    logger.info("Seeding users...")
    users_to_seed = [
        ("admin@nexafreight.local", "admin123", "System Administrator", UserRole.ADMIN),
        ("operator@nexafreight.local", "operator123", "Operations Manager", UserRole.OPERATOR),
        ("viewer@nexafreight.local", "viewer123", "Dashboard Viewer", UserRole.VIEWER),
        ("operator@nexafreight.dev", "changeme123", "Dev Operator", UserRole.OPERATOR),
    ]
    for email, pwd, name, role in users_to_seed:
        res = await session.execute(select(User).where(User.email == email))
        if not res.scalar_one_or_none():
            u = User(
                email=email,
                hashed_password=hash_password(pwd, settings),
                full_name=name,
                role=role,
                is_active=True,
            )
            session.add(u)
    await session.flush()

    # -------------------------------------------------------------------------
    # 2. Locations (Ports)
    # -------------------------------------------------------------------------
    logger.info("Seeding locations and ports...")
    port_defs = [
        ("CNSHA", "Shanghai Port", "CN", 31.23, 121.47, 0.72),
        ("NLRTM", "Rotterdam Port", "NL", 51.92, 4.48, 0.85),
        ("SGSIN", "Singapore Port", "SG", 1.35, 103.82, 0.38),
        ("DEHAM", "Hamburg Port", "DE", 53.55, 9.99, 0.42),
        ("USNYC", "Port of New York / New Jersey", "US", 40.71, -74.01, 0.55),
        ("USLAX", "Port of Los Angeles", "US", 33.74, -118.27, 0.68),
        ("AEJEA", "Jebel Ali Port (Dubai)", "AE", 25.01, 55.06, 0.31),
        ("JPTYO", "Tokyo Port", "JP", 35.68, 139.76, 0.25),
    ]

    loc_map: dict[str, Location] = {}
    for locode, name, cc, lat, lon, congestion in port_defs:
        res = await session.execute(select(Location).where(Location.locode == locode))
        loc = res.scalar_one_or_none()
        if not loc:
            loc = Location(
                locode=locode,
                name=name,
                country_code=cc,
                location_type=LocationType.PORT,
                latitude=lat,
                longitude=lon,
            )
            session.add(loc)
            await session.flush()

            port = Port(location_id=loc.id)
            session.add(port)
            await session.flush()

            stat = PortDailyStat(
                port_id=port.id,
                stat_date=date.today(),
                congestion_index=congestion,
            )
            session.add(stat)
        loc_map[locode] = loc

    await session.flush()

    # -------------------------------------------------------------------------
    # 3. Vessels
    # -------------------------------------------------------------------------
    logger.info("Seeding vessels...")
    vessels_data = [
        (211000001, "Nexa Voyager", "NX-101", json.dumps(["Asia-Europe", "Trans-Pacific"])),
        (211000002, "Nexa Horizon", "NX-102", json.dumps(["Asia-Middle East", "Europe-US"])),
        (211000003, "Pacific Carrier", "PC-301", json.dumps(["Trans-Pacific"])),
        (211000004, "Atlantic Pioneer", "AP-401", json.dumps(["Trans-Atlantic"])),
    ]
    vessel_map: dict[int, Vessel] = {}
    for mmsi, name, call_sign, lanes in vessels_data:
        res = await session.execute(select(Vessel).where(Vessel.mmsi == mmsi))
        vessel = res.scalar_one_or_none()
        if not vessel:
            vessel = Vessel(
                mmsi=mmsi,
                name=name,
                call_sign=call_sign,
                typical_lanes_json=lanes,
            )
            session.add(vessel)
            await session.flush()
        vessel_map[mmsi] = vessel

    await session.flush()

    # -------------------------------------------------------------------------
    # 4. Shipments & Legs
    # -------------------------------------------------------------------------
    logger.info("Seeding shipments, legs, and positions...")
    shipment_defs = [
        {
            "id": str(uuid.uuid4()),
            "origin": "CNSHA",
            "destination": "NLRTM",
            "mode": TransportMode.SEA,
            "cargo": CargoClass.STANDARD,
            "vessel_mmsi": 211000001,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -14,  # days ago
            "arrival_delta": 4,      # days ahead
            "cur_lat": 22.5,
            "cur_lon": 60.0,
            "heading": 285.0,
            "speed": 18.5,
            "waypoints": [
                [121.47, 31.23],
                [103.82, 1.35],
                [80.0, 5.0],
                [60.0, 22.5],
                [43.0, 12.5],
                [32.5, 30.0],
                [-5.5, 36.0],
                [4.48, 51.92],
            ],
            "revenue": 54000.0,
            "scheduled_days": 20,
            "disrupt": True,
        },
        {
            "id": str(uuid.uuid4()),
            "origin": "DEHAM",
            "destination": "USNYC",
            "mode": TransportMode.SEA,
            "cargo": CargoClass.HIGH_VALUE,
            "vessel_mmsi": 211000004,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -5,
            "arrival_delta": 3,
            "cur_lat": 47.5,
            "cur_lon": -35.0,
            "heading": 260.0,
            "speed": 19.2,
            "waypoints": [
                [9.99, 53.55],
                [1.5, 51.0],
                [-20.0, 48.0],
                [-35.0, 47.5],
                [-55.0, 43.0],
                [-74.01, 40.71],
            ],
            "revenue": 38000.0,
            "scheduled_days": 9,
            "disrupt": False,
        },
        {
            "id": str(uuid.uuid4()),
            "origin": "SGSIN",
            "destination": "AEJEA",
            "mode": TransportMode.SEA,
            "cargo": CargoClass.REFRIGERATED,
            "vessel_mmsi": 211000002,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -3,
            "arrival_delta": 2,
            "cur_lat": 15.2,
            "cur_lon": 68.4,
            "heading": 305.0,
            "speed": 16.8,
            "waypoints": [
                [103.82, 1.35],
                [95.0, 6.0],
                [80.0, 9.0],
                [68.4, 15.2],
                [58.0, 22.0],
                [55.06, 25.01],
            ],
            "revenue": 42000.0,
            "scheduled_days": 7,
            "disrupt": False,
        },
        {
            "id": str(uuid.uuid4()),
            "origin": "JPTYO",
            "destination": "USLAX",
            "mode": TransportMode.SEA,
            "cargo": CargoClass.STANDARD,
            "vessel_mmsi": 211000003,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -7,
            "arrival_delta": 5,
            "cur_lat": 36.8,
            "cur_lon": -165.0,
            "heading": 98.0,
            "speed": 21.0,
            "waypoints": [
                [139.76, 35.68],
                [160.0, 38.0],
                [-180.0, 40.0],
                [-165.0, 36.8],
                [-140.0, 34.5],
                [-118.27, 33.74],
            ],
            "revenue": 76000.0,
            "scheduled_days": 14,
            "disrupt": False,
        },
        {
            "id": str(uuid.uuid4()),
            "origin": "USNYC",
            "destination": "USLAX",
            "mode": TransportMode.ROAD,
            "cargo": CargoClass.STANDARD,
            "vessel_mmsi": None,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -2,
            "arrival_delta": 1,
            "cur_lat": 38.5,
            "cur_lon": -98.2,
            "heading": 255.0,
            "speed": 55.0,
            "waypoints": [
                [-74.01, 40.71],
                [-84.0, 39.0],
                [-98.2, 38.5],
                [-110.0, 36.0],
                [-118.27, 33.74],
            ],
            "revenue": 14500.0,
            "scheduled_days": 4,
            "disrupt": False,
        },
        {
            "id": str(uuid.uuid4()),
            "origin": "CNSHA",
            "destination": "DEHAM",
            "mode": TransportMode.AIR,
            "cargo": CargoClass.HIGH_VALUE,
            "vessel_mmsi": None,
            "status": ShipmentStatus.IN_TRANSIT,
            "departure_delta": -1,
            "arrival_delta": 1,
            "cur_lat": 52.0,
            "cur_lon": 45.0,
            "heading": 290.0,
            "speed": 480.0,
            "waypoints": [
                [121.47, 31.23],
                [85.0, 45.0],
                [45.0, 52.0],
                [20.0, 53.0],
                [9.99, 53.55],
            ],
            "revenue": 62000.0,
            "scheduled_days": 2,
            "disrupt": False,
        },
    ]

    # Check if shipments already exist
    res = await session.execute(select(Shipment))
    existing_shipments = res.scalars().all()
    if existing_shipments:
        logger.info(f"Database already contains {len(existing_shipments)} shipments. Skipping shipment creation.")
        return

    for s_data in shipment_defs:
        o_loc = loc_map[s_data["origin"]]
        d_loc = loc_map[s_data["destination"]]
        dep_time = now + timedelta(days=s_data["departure_delta"])
        arr_time = now + timedelta(days=s_data["arrival_delta"])
        deadline = dep_time + timedelta(days=s_data["scheduled_days"])

        shipment = Shipment(
            id=s_data["id"],
            provenance=Provenance.SIMULATED,
            origin_id=o_loc.id,
            destination_id=d_loc.id,
            primary_transport_mode=s_data["mode"],
            cargo_class=s_data["cargo"],
            container_count=2,
            status=s_data["status"],
            route_version=1,
            planned_departure=dep_time,
            strictest_sla_deadline=deadline,
        )
        session.add(shipment)
        await session.flush()

        # Leg
        geom = {
            "type": "LineString",
            "coordinates": s_data["waypoints"],
        }
        vessel_id = vessel_map[s_data["vessel_mmsi"]].id if s_data["vessel_mmsi"] else None
        leg = Leg(
            shipment_id=shipment.id,
            sequence_number=1,
            route_version=1,
            transport_mode=s_data["mode"],
            status=LegStatus.IN_PROGRESS,
            origin_id=o_loc.id,
            destination_id=d_loc.id,
            planned_departure=dep_time,
            planned_arrival=arr_time,
            actual_departure=dep_time,
            vessel_id=vessel_id,
            route_geometry_json=json.dumps(geom),
            provenance=Provenance.SIMULATED,
        )
        session.add(leg)
        await session.flush()

        # Position report
        pos = PositionReport(
            leg_id=leg.id,
            asset_type=s_data["mode"].lower(),
            mmsi=s_data["vessel_mmsi"],
            latitude=s_data["cur_lat"],
            longitude=s_data["cur_lon"],
            heading=s_data["heading"],
            speed_knots=s_data["speed"],
            reported_at=now,
            provenance=Provenance.SIMULATED,
        )
        session.add(pos)

        # Order & items
        order = Order(
            shipment_id=shipment.id,
            order_number=f"ORD-{shipment.id[:8].upper()}",
            order_date=dep_time,
            sla_deadline=deadline,
            sla_status=OrderSlaStatus.ON_TIME,
            shipping_mode=s_data["mode"],
            cargo_class=s_data["cargo"],
            revenue=s_data["revenue"],
            shipping_cost=s_data["revenue"] * 0.35,
        )
        session.add(order)
        await session.flush()

        item = OrderItem(
            order_id=order.id,
            product_category=f"Category {s_data['cargo']}",
            quantity=100,
            unit_price=s_data["revenue"] / 100,
        )
        session.add(item)

        # Create disruption & alert if flagged
        if s_data["disrupt"]:
            disruption = Disruption(
                shipment_id=shipment.id,
                leg_id=leg.id,
                disruption_type=DisruptionType.PORT_CONGESTION,
                status=DisruptionStatus.ACTIVE,
                description=f"Severe port congestion at destination ({d_loc.name}). Estimated delay +36 hours.",
                detected_at=now,
            )
            session.add(disruption)
            await session.flush()

            alert = Alert(
                disruption_id=disruption.id,
                shipment_id=shipment.id,
                severity=AlertSeverity.CRITICAL,
                status=AlertStatus.OPEN,
                financial_exposure=18500.0,
                sla_breach_details_json=json.dumps({
                    "orders_affected": 1,
                    "penalty_exposure_usd": 12500.0,
                    "demurrage_exposure_usd": 6000.0,
                    "predicted_breach_hours": 36.0,
                }),
            )
            session.add(alert)

    await session.commit()
    logger.info("Demo data seeding completed successfully! All entities created.")


async def main() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        await seed_all(session)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
