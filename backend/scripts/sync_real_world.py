#!/usr/bin/env python3
"""Sync Real-World Operations & Multimodal Fleet Orchestrator.

Synchronizes NexaFreight with the real DataCo Supply Chain dataset,
replays multimodal trade corridors (SEA, AIR, ROAD, RAIL) with realistic
temporal horizons around world_now(), seeds live in-transit telemetry,
and attaches active disruption triage alerts.

Usage:
    python scripts/sync_real_world.py [--limit 250] [--seed 42] [--clean]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add backend and src to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "src"))
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select, update
from nexafreight.core.clock import world_now
from nexafreight.database import get_session_factory
from nexafreight.enums import (
    AlertSeverity,
    AlertStatus,
    CargoClass,
    DisruptionStatus,
    DisruptionType,
    LegStatus,
    OrderSlaStatus,
    Provenance,
    ShipmentStatus,
    TransportMode,
)
from nexafreight.models.alert import Alert
from nexafreight.models.disruption import Disruption
from nexafreight.models.leg import Leg
from nexafreight.models.order import Order
from nexafreight.models.position_report import PositionReport
from nexafreight.models.shipment import Shipment
from nexafreight.workers.position_interpolator import _LegData, _interpolate_linear

# Load 27_replay_dataco_corridors dynamically
import importlib.util
spec = importlib.util.spec_from_file_location(
    "replay_dataco",
    str(BACKEND_DIR / "scripts" / "27_replay_dataco_corridors.py"),
)
replay_dataco = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_dataco)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_real_world")


DISRUPTION_SCENARIOS = [
    {
        "type": DisruptionType.VESSEL_DELAY,
        "title": "Bab-el-Mandeb Strait Security Advisory",
        "description": "Red Sea security advisory: container vessel rerouting via Cape of Good Hope or awaiting armed convoy escort in Suez queue; +72h delay.",
        "severity": AlertSeverity.CRITICAL,
        "mode": TransportMode.SEA,
    },
    {
        "type": DisruptionType.PORT_CONGESTION,
        "title": "JNPT Nhava Sheva Terminal Congestion",
        "description": "Berth congestion at Jawaharlal Nehru Port container terminal 4: vessel dwell elevated +36h above historical baseline.",
        "severity": AlertSeverity.HIGH,
        "mode": TransportMode.SEA,
    },
    {
        "type": DisruptionType.WEATHER,
        "title": "Bay of Bengal Monsoon Squall",
        "description": "Severe tropical depression in North Bay of Bengal: container vessel throttling to safe speed; wave height exceeding 5.2m; +24h delay.",
        "severity": AlertSeverity.HIGH,
        "mode": TransportMode.SEA,
    },
    {
        "type": DisruptionType.PORT_CONGESTION,
        "title": "Port of Rotterdam Barge Terminal Strike",
        "description": "Labor union 48-hour stoppage on Maasvlakte feeder berths: inbound container transshipment delayed +48h.",
        "severity": AlertSeverity.CRITICAL,
        "mode": TransportMode.SEA,
    },
    {
        "type": DisruptionType.MANUAL,
        "title": "Delhi Tughlakabad ICD Inspection Hold",
        "description": "Mandatory risk assessment scan hold by customs authority at Tughlakabad Inland Container Depot; +18h dwell.",
        "severity": AlertSeverity.MEDIUM,
        "mode": TransportMode.RAIL,
    },
    {
        "type": DisruptionType.WEATHER,
        "title": "Mumbai-Delhi Air Corridor Weather Throttling",
        "description": "Dense fog and thunderstorm advisory at IGI Airport Delhi: air cargo freighter delayed in holding pattern; +6h.",
        "severity": AlertSeverity.MEDIUM,
        "mode": TransportMode.AIR,
    },
]


async def seed_active_telemetry(session, world: datetime) -> int:
    """Calculate and write PositionReport rows for all currently IN_PROGRESS legs."""
    stmt = (
        select(Leg)
        .where((Leg.status == LegStatus.IN_PROGRESS) | (Leg.status == "IN_PROGRESS"))
        .where(Leg.route_geometry_json.isnot(None))
    )
    legs = (await session.execute(stmt)).scalars().all()
    
    seeded_count = 0
    for leg in legs:
        if not leg.route_geometry_json:
            continue
        try:
            mode_val = leg.transport_mode.value if hasattr(leg.transport_mode, "value") else str(leg.transport_mode)
            leg_dto = _LegData(
                leg_id=leg.id,
                mode=mode_val,
                route_geometry=leg.route_geometry_json,
                planned_departure=leg.planned_departure,
                planned_arrival=leg.planned_arrival,
                actual_departure=leg.actual_departure or leg.planned_departure,
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
                seeded_count += 1
        except Exception as exc:
            log.debug("Error computing position for leg %s: %s", leg.id, exc)

    await session.commit()
    return seeded_count


async def attach_disruption_scenarios(session, world: datetime, count: int = 6) -> int:
    """Find active DELAYED or IN_TRANSIT shipments and attach realistic Disruption + Alert records."""
    stmt = (
        select(Shipment)
        .where(Shipment.status.in_([ShipmentStatus.DELAYED, ShipmentStatus.IN_TRANSIT, "DELAYED", "IN_TRANSIT"]))
        .order_by(Shipment.created_at.desc())
        .limit(30)
    )
    candidates = (await session.execute(stmt)).scalars().all()
    if not candidates:
        log.warning("No candidate shipments found for disruption attachment.")
        return 0

    existing_shipment_ids = set(
        (await session.execute(select(Disruption.shipment_id))).scalars().all()
    )

    created_alerts = 0
    rng = random.Random(42)
    selected = [s for s in candidates if s.id not in existing_shipment_ids][:count]

    for idx, shipment in enumerate(selected):
        scenario = DISRUPTION_SCENARIOS[idx % len(DISRUPTION_SCENARIOS)]
        
        leg_stmt = (
            select(Leg)
            .where(Leg.shipment_id == shipment.id)
            .where(Leg.status.in_([LegStatus.IN_PROGRESS, "IN_PROGRESS", LegStatus.PLANNED, "PLANNED"]))
            .order_by(Leg.sequence_number.asc())
        )
        leg = (await session.execute(leg_stmt)).scalars().first()
        leg_id = leg.id if leg else None

        disruption_id = str(uuid.uuid4())
        alert_id = str(uuid.uuid4())

        exposure = round(float(shipment.container_count or 1) * 5500.0 * rng.uniform(2.5, 6.0), 2)

        disruption = Disruption(
            id=disruption_id,
            shipment_id=shipment.id,
            leg_id=leg_id,
            disruption_type=scenario["type"],
            status=DisruptionStatus.ACTIVE,
            description=scenario["description"],
            detected_at=world - timedelta(hours=rng.randint(2, 24)),
        )

        alert = Alert(
            id=alert_id,
            disruption_id=disruption_id,
            shipment_id=shipment.id,
            severity=scenario["severity"],
            status=AlertStatus.OPEN,
            financial_exposure=exposure,
            sla_breach_details_json=json.dumps({
                "title": scenario["title"],
                "projected_delay_hours": rng.randint(24, 72),
                "demurrage_exposure_inr": exposure,
                "contingency_options": ["PORT_DIVERT", "MODAL_SHIFT", "ACCEPT_DELAY"],
            }),
        )

        shipment.status = ShipmentStatus.DELAYED

        session.add_all([disruption, alert])
        created_alerts += 1

    await session.commit()
    return created_alerts


async def run_sync(limit: int = 250, top: int = 8, seed: int = 42, clean_replayed: bool = False):
    """Main synchronization pipeline."""
    world = world_now()
    log.info("═══════════════════════════════════════════════════════════════")
    log.info("  NexaFreight Real-World Sync & Multimodal Fleet Orchestrator  ")
    log.info("  Anchor Timestamp: %s", world.isoformat())
    log.info("═══════════════════════════════════════════════════════════════")

    factory = get_session_factory()

    # Step 1: Optional clean of past replayed DC- orders
    if clean_replayed:
        async with factory() as session:
            log.info("Cleaning previous DC- replayed orders...")
            dc_orders = (await session.execute(
                select(Order.id, Order.shipment_id).where(Order.order_number.like("DC-%"))
            )).all()
            if dc_orders:
                shipment_ids = [row.shipment_id for row in dc_orders if row.shipment_id]
                from sqlalchemy import text
                await session.execute(text("PRAGMA foreign_keys = OFF;"))
                await session.execute(delete(PositionReport).where(PositionReport.leg_id.in_(
                    select(Leg.id).where(Leg.shipment_id.in_(shipment_ids))
                )))
                await session.execute(delete(Alert).where(Alert.shipment_id.in_(shipment_ids)))
                await session.execute(delete(Disruption).where(Disruption.shipment_id.in_(shipment_ids)))
                await session.execute(delete(Leg).where(Leg.shipment_id.in_(shipment_ids)))
                await session.execute(delete(Order).where(Order.order_number.like("DC-%")))
                await session.execute(delete(Shipment).where(Shipment.id.in_(shipment_ids)))
                await session.commit()
                await session.execute(text("PRAGMA foreign_keys = ON;"))
                log.info("Cleaned %d past replayed shipments.", len(shipment_ids))

    # Step 2: Run DataCo corridor replay with live mix
    log.info("Replaying DataCo corridors with dynamic live-mix temporal distribution...")
    replay_args = argparse.Namespace(
        dataco=BACKEND_DIR / "data" / "raw" / "dataco" / "DataCoSupplyChain.csv",
        limit=limit,
        top=top,
        days_back=21,
        seed=seed,
        dry_run=False,
        live_mix=True,
        in_transit_ratio=0.45,
        delayed_ratio=0.15,
        delivered_ratio=0.25,
        db_url=None,
    )

    await replay_dataco.run(replay_args)

    # Step 3: Seed in-transit telemetry
    log.info("Calculating and seeding in-transit telemetry for active legs...")
    async with factory() as session:
        telemetry_count = await seed_active_telemetry(session, world)
        log.info("Seeded %d active position reports across world fleet.", telemetry_count)

    # Step 4: Attach active disruption scenarios
    log.info("Linking active delayed shipments to operational disruption scenarios...")
    async with factory() as session:
        alerts_count = await attach_disruption_scenarios(session, world, count=6)
        log.info("Created %d active triage alerts with financial exposure.", alerts_count)

    # Step 5: Report Summary
    async with factory() as session:
        total_shipments = (await session.execute(select(func.count(Shipment.id)))).scalar() or 0
        total_legs = (await session.execute(select(func.count(Leg.id)))).scalar() or 0
        active_legs = (await session.execute(select(func.count(Leg.id)).where(Leg.status == LegStatus.IN_PROGRESS))).scalar() or 0
        active_positions = (await session.execute(select(func.count(PositionReport.id)))).scalar() or 0
        active_alerts = (await session.execute(select(func.count(Alert.id)).where(Alert.status == AlertStatus.OPEN))).scalar() or 0

    log.info("═══════════════════════════════════════════════════════════════")
    log.info("  SYNC COMPLETE: Operational World Summary                      ")
    log.info("  • Total Shipments in System : %d", total_shipments)
    log.info("  • Total Route Legs          : %d", total_legs)
    log.info("  • Active IN_PROGRESS Legs   : %d", active_legs)
    log.info("  • Live Position Reports     : %d", active_positions)
    log.info("  • Active Disruption Alerts  : %d", active_alerts)
    log.info("═══════════════════════════════════════════════════════════════")


def main():
    parser = argparse.ArgumentParser(description="Synchronize NexaFreight with real-world DataCo corridors and fleet telemetry.")
    parser.add_argument("--limit", type=int, default=200, help="Number of DataCo orders to replay")
    parser.add_argument("--top", type=int, default=8, help="Number of top corridors to sample from")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--clean", action="store_true", help="Clean previously replayed DC- orders before sync")
    args = parser.parse_args()

    asyncio.run(run_sync(limit=args.limit, top=args.top, seed=args.seed, clean_replayed=args.clean))


if __name__ == "__main__":
    main()
