import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, date

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text
from nexafreight.database import create_async_engine

def parse_dt(val):
    if not val:
        return None
    if isinstance(val, (datetime, date)):
        return val
    s = str(val).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def clean_dict(row, dt_cols):
    d = dict(row)
    for col in dt_cols:
        if col in d:
            d[col] = parse_dt(d[col])
    return d

async def sync():
    sqlite_path = Path(__file__).resolve().parent.parent / "data" / "nexafreight.db"
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in environment.", flush=True)
        return

    print("Connecting to Neon PostgreSQL...", flush=True)
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        print("Connected. Starting synchronization...", flush=True)

        # ---------------------------------------------------------
        # 1. Sync Locations needed by operational data
        # ---------------------------------------------------------
        loc_ids_query = cur.execute("""
            SELECT DISTINCT origin_id FROM shipments WHERE status IN ('DELAYED', 'IN_TRANSIT', 'DELIVERED') OR id IN (SELECT DISTINCT shipment_id FROM legs)
            UNION
            SELECT DISTINCT destination_id FROM shipments WHERE status IN ('DELAYED', 'IN_TRANSIT', 'DELIVERED') OR id IN (SELECT DISTINCT shipment_id FROM legs)
            UNION
            SELECT DISTINCT origin_id FROM legs
            UNION
            SELECT DISTINCT destination_id FROM legs
        """).fetchall()
        needed_loc_ids = [r[0] for r in loc_ids_query if r[0] is not None]
        print(f"Needed locations count: {len(needed_loc_ids)}", flush=True)

        # Map to remap sqlite location IDs -> neon location IDs
        loc_id_map = {}

        if needed_loc_ids:
            loc_placeholders = ",".join(str(i) for i in needed_loc_ids)
            sqlite_locs = cur.execute(f"SELECT * FROM locations WHERE id IN ({loc_placeholders})").fetchall()
            locodes = [l["locode"] for l in sqlite_locs]

            # Check existing locodes in Neon
            existing_neon = await conn.execute(
                text("SELECT id, locode FROM locations WHERE locode = ANY(:locodes)"),
                {"locodes": locodes}
            )
            neon_loc_by_locode = {row[1]: row[0] for row in existing_neon.fetchall()}

            for sloc in sqlite_locs:
                sloc_id = sloc["id"]
                sloc_code = sloc["locode"]
                if sloc_code in neon_loc_by_locode:
                    loc_id_map[sloc_id] = neon_loc_by_locode[sloc_code]
                else:
                    # Insert missing custom location into Neon
                    res = await conn.execute(text("""
                        INSERT INTO locations (locode, name, country_code, location_type, latitude, longitude, created_at, updated_at)
                        VALUES (:locode, :name, :country_code, :location_type, :latitude, :longitude, :created_at, :updated_at)
                        ON CONFLICT (locode) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                    """), {
                        "locode": sloc["locode"],
                        "name": sloc["name"],
                        "country_code": sloc["country_code"],
                        "location_type": sloc["location_type"],
                        "latitude": sloc["latitude"],
                        "longitude": sloc["longitude"],
                        "created_at": parse_dt(sloc["created_at"]),
                        "updated_at": parse_dt(sloc["updated_at"])
                    })
                    new_id = res.scalar()
                    loc_id_map[sloc_id] = new_id
                    print(f"  Inserted custom location '{sloc_code}' -> Neon ID {new_id}", flush=True)

        print(f"Location mapping established for {len(loc_id_map)} locations.", flush=True)

        # ---------------------------------------------------------
        # 2. Sync Vessels
        # ---------------------------------------------------------
        vessels = [clean_dict(v, ["created_at", "updated_at"]) for v in cur.execute("SELECT * FROM vessels").fetchall()]
        print(f"Syncing {len(vessels)} vessels...", flush=True)
        if vessels:
            await conn.execute(text("""
                INSERT INTO vessels (id, mmsi, name, call_sign, typical_lanes_json, created_at, updated_at)
                VALUES (:id, :mmsi, :name, :call_sign, :typical_lanes_json, :created_at, :updated_at)
                ON CONFLICT (mmsi) DO UPDATE SET 
                    name = EXCLUDED.name,
                    call_sign = EXCLUDED.call_sign,
                    typical_lanes_json = EXCLUDED.typical_lanes_json
            """), vessels)

        # Map vessel MMSI/ID to Neon vessel ID
        neon_vessels = await conn.execute(text("SELECT id, mmsi FROM vessels"))
        vessel_mmsi_to_neon_id = {row[1]: row[0] for row in neon_vessels.fetchall()}
        vessel_id_map = {}
        for v in vessels:
            if v["mmsi"] in vessel_mmsi_to_neon_id:
                vessel_id_map[v["id"]] = vessel_mmsi_to_neon_id[v["mmsi"]]

        # ---------------------------------------------------------
        # 3. Sync Operational Shipments
        # ---------------------------------------------------------
        shipments_raw = cur.execute("""
            SELECT * FROM shipments 
            WHERE status IN ('DELAYED', 'IN_TRANSIT', 'DELIVERED')
               OR id IN (SELECT DISTINCT shipment_id FROM legs)
               OR id IN (SELECT DISTINCT shipment_id FROM disruptions)
        """).fetchall()
        shipments = []
        for s in shipments_raw:
            sd = clean_dict(s, ["planned_departure", "strictest_sla_deadline", "created_at", "updated_at"])
            sd["origin_id"] = loc_id_map.get(sd["origin_id"], sd["origin_id"])
            sd["destination_id"] = loc_id_map.get(sd["destination_id"], sd["destination_id"])
            shipments.append(sd)

        print(f"Syncing {len(shipments)} operational shipments...", flush=True)
        if shipments:
            await conn.execute(text("""
                INSERT INTO shipments (
                    id, origin_id, destination_id, primary_transport_mode, cargo_class,
                    container_count, status, route_version, planned_departure,
                    strictest_sla_deadline, parent_shipment_id, provenance, created_at, updated_at
                ) VALUES (
                    :id, :origin_id, :destination_id, :primary_transport_mode, :cargo_class,
                    :container_count, :status, :route_version, :planned_departure,
                    :strictest_sla_deadline, :parent_shipment_id, :provenance, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    planned_departure = EXCLUDED.planned_departure,
                    strictest_sla_deadline = EXCLUDED.strictest_sla_deadline,
                    container_count = EXCLUDED.container_count,
                    origin_id = EXCLUDED.origin_id,
                    destination_id = EXCLUDED.destination_id,
                    updated_at = EXCLUDED.updated_at
            """), shipments)

        # ---------------------------------------------------------
        # 4. Sync Legs
        # ---------------------------------------------------------
        legs_raw = cur.execute("SELECT * FROM legs").fetchall()
        legs = []
        for l in legs_raw:
            ld = clean_dict(l, ["planned_departure", "planned_arrival", "actual_departure", "actual_arrival", "created_at", "updated_at"])
            ld["origin_id"] = loc_id_map.get(ld["origin_id"], ld["origin_id"])
            ld["destination_id"] = loc_id_map.get(ld["destination_id"], ld["destination_id"])
            if ld.get("vessel_id") and ld["vessel_id"] in vessel_id_map:
                ld["vessel_id"] = vessel_id_map[ld["vessel_id"]]
            legs.append(ld)

        print(f"Syncing {len(legs)} legs...", flush=True)
        if legs:
            await conn.execute(text("""
                INSERT INTO legs (
                    id, shipment_id, sequence_number, route_version, transport_mode,
                    status, origin_id, destination_id, vessel_id, flight_number,
                    planned_departure, planned_arrival, actual_departure, actual_arrival,
                    route_geometry_json, distance_km, co2_kg, provenance, created_at, updated_at
                ) VALUES (
                    :id, :shipment_id, :sequence_number, :route_version, :transport_mode,
                    :status, :origin_id, :destination_id, :vessel_id, :flight_number,
                    :planned_departure, :planned_arrival, :actual_departure, :actual_arrival,
                    :route_geometry_json, :distance_km, :co2_kg, :provenance, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    origin_id = EXCLUDED.origin_id,
                    destination_id = EXCLUDED.destination_id,
                    vessel_id = EXCLUDED.vessel_id,
                    route_geometry_json = EXCLUDED.route_geometry_json,
                    distance_km = EXCLUDED.distance_km,
                    co2_kg = EXCLUDED.co2_kg,
                    updated_at = EXCLUDED.updated_at
            """), legs)

        # ---------------------------------------------------------
        # 5. Sync Disruptions
        # ---------------------------------------------------------
        disruptions = [clean_dict(d, ["detected_at", "resolved_at", "created_at", "updated_at"]) for d in cur.execute("SELECT * FROM disruptions").fetchall()]
        print(f"Syncing {len(disruptions)} disruptions...", flush=True)
        if disruptions:
            await conn.execute(text("""
                INSERT INTO disruptions (
                    id, shipment_id, leg_id, disruption_type, status,
                    description, detected_at, resolved_at, created_at, updated_at
                ) VALUES (
                    :id, :shipment_id, :leg_id, :disruption_type, :status,
                    :description, :detected_at, :resolved_at, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    description = EXCLUDED.description,
                    resolved_at = EXCLUDED.resolved_at,
                    updated_at = EXCLUDED.updated_at
            """), disruptions)

        # ---------------------------------------------------------
        # 6. Sync Alerts
        # ---------------------------------------------------------
        alerts = [clean_dict(a, ["acknowledged_at", "created_at", "updated_at"]) for a in cur.execute("SELECT * FROM alerts").fetchall()]
        print(f"Syncing {len(alerts)} alerts...", flush=True)
        if alerts:
            await conn.execute(text("""
                INSERT INTO alerts (
                    id, disruption_id, shipment_id, severity, status,
                    financial_exposure, sla_breach_details_json, acknowledged_by,
                    acknowledged_at, created_at, updated_at
                ) VALUES (
                    :id, :disruption_id, :shipment_id, :severity, :status,
                    :financial_exposure, :sla_breach_details_json, :acknowledged_by,
                    :acknowledged_at, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    severity = EXCLUDED.severity,
                    status = EXCLUDED.status,
                    financial_exposure = EXCLUDED.financial_exposure,
                    sla_breach_details_json = EXCLUDED.sla_breach_details_json,
                    updated_at = EXCLUDED.updated_at
            """), alerts)

        # ---------------------------------------------------------
        # 7. Sync Position Reports (latest 500 for active tracking)
        # ---------------------------------------------------------
        pos_raw = cur.execute("""
            SELECT * FROM position_reports 
            ORDER BY reported_at DESC LIMIT 500
        """).fetchall()
        pos_reports = [clean_dict(p, ["reported_at"]) for p in pos_raw]
        print(f"Syncing {len(pos_reports)} latest position reports...", flush=True)
        if pos_reports:
            await conn.execute(text("""
                INSERT INTO position_reports (
                    id, leg_id, asset_type, mmsi, latitude, longitude,
                    heading, speed_knots, reported_at, provenance
                ) VALUES (
                    :id, :leg_id, :asset_type, :mmsi, :latitude, :longitude,
                    :heading, :speed_knots, :reported_at, :provenance
                )
                ON CONFLICT (id) DO NOTHING
            """), pos_reports)

        # ---------------------------------------------------------
        # 8. Sync Orders for operational shipments
        # ---------------------------------------------------------
        shipment_ids = [s["id"] for s in shipments]
        if shipment_ids:
            placeholders = ",".join(f"'{sid}'" for sid in shipment_ids)
            orders_raw = cur.execute(f"SELECT * FROM orders WHERE shipment_id IN ({placeholders})").fetchall()
            orders = [clean_dict(o, ["order_date", "sla_deadline", "created_at", "updated_at"]) for o in orders_raw]
            print(f"Syncing {len(orders)} orders...", flush=True)
            if orders:
                await conn.execute(text("""
                    INSERT INTO orders (
                        shipment_id, order_number, order_date, sla_deadline,
                        sla_status, shipping_mode, cargo_class, revenue, shipping_cost,
                        created_at, updated_at
                    ) VALUES (
                        :shipment_id, :order_number, :order_date, :sla_deadline,
                        :sla_status, :shipping_mode, :cargo_class, :revenue, :shipping_cost,
                        :created_at, :updated_at
                    )
                    ON CONFLICT (order_number) DO UPDATE SET
                        shipment_id = EXCLUDED.shipment_id,
                        order_date = EXCLUDED.order_date,
                        sla_deadline = EXCLUDED.sla_deadline,
                        sla_status = EXCLUDED.sla_status,
                        shipping_mode = EXCLUDED.shipping_mode,
                        cargo_class = EXCLUDED.cargo_class,
                        revenue = EXCLUDED.revenue,
                        shipping_cost = EXCLUDED.shipping_cost,
                        updated_at = EXCLUDED.updated_at
                """), orders)

    await engine.dispose()
    print("ALL OPERATIONAL DATA SUCCESSFULLY SYNCHRONIZED TO NEON POSTGRESQL!", flush=True)

if __name__ == "__main__":
    asyncio.run(sync())
