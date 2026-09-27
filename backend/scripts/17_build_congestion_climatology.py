#!/usr/bin/env python3
"""Build port-congestion month-of-year climatology tables (Task 15).

Reads PortDailyStat rows from the database (today: the demo world's
SIMULATED stats; later: real PortWatch pulls through the same table) and
writes a JSON pattern table per port for months with sufficient coverage.

The table feeds the task-15 congestion features (services contract:
ml.feature_contract) — v2 training consumes it; the v1 champion is
untouched.

Usage:
    PYTHONPATH=src python scripts/17_build_congestion_climatology.py \
        [--min-days 30] [--source simulated] [--input-source all]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "src"))

from sqlalchemy import select  # noqa: E402

from nexafreight.database import get_session_factory  # noqa: E402
from nexafreight.enums import NodeType  # noqa: E402
from nexafreight.ml.feature_contract import build_climatology  # noqa: E402
from nexafreight.models.location import Location  # noqa: E402
from nexafreight.models.network import NetworkNode  # noqa: E402
from nexafreight.models.port import Port, PortDailyStat  # noqa: E402

OUTPUT_PATH = BACKEND / "models" / "congestion" / "climatology.json"


async def load_stats(session, input_source: str) -> "pd.DataFrame":  # noqa: F821
    import pandas as pd

    # Port.locode is a property over the Location relationship (E25): join
    # Location explicitly. Node-type filter excludes the stale AIRPORT-derived
    # Port rows left by the first seeder run (day-6 quirk).
    query = (
        select(Location.locode, PortDailyStat.stat_date, PortDailyStat.congestion_index)
        .join(Port, Port.location_id == Location.id)
        .join(PortDailyStat, PortDailyStat.port_id == Port.id)
        .join(NetworkNode, NetworkNode.locode == Location.locode)
        .where(NetworkNode.node_type == NodeType.PORT.value)
    )
    if input_source != "all":
        query = query.where(PortDailyStat.source == input_source.upper())

    rows = (await session.execute(query)).all()
    return pd.DataFrame(rows, columns=["port_locode", "stat_date", "congestion_index"])


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-days", type=int, default=30)
    ap.add_argument(
        "--source",
        choices=["simulated", "portwatch", "calibrated"],
        default="simulated",
        help="provenance label for the output table",
    )
    ap.add_argument(
        "--input-source",
        choices=["simulated", "portwatch", "calibrated", "all"],
        default="all",
        help="filter input data by this source (default: all)",
    )
    args = ap.parse_args()

    factory = get_session_factory()
    try:
        async with factory() as session:
            stats = await load_stats(session, args.input_source)
    except Exception as exc:
        print(
            f"database unavailable ({exc.__class__.__name__}) - build the demo "
            "world first (scripts/20) and run from backend/"
        )
        return 2
    if stats.empty:
        print("no PortDailyStat rows (build the demo world first: scripts/20)")
        return 2

    table = build_climatology(stats, min_days_per_month=args.min_days)
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": args.source.upper(),
        "input_source": args.input_source.upper(),
        "min_days_per_month": args.min_days,
        "observation_rows": int(len(stats)),
        "input_rows": int(len(stats)),
        "ports": table,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"climatology written: {OUTPUT_PATH.relative_to(BACKEND)}")
    for port, months in table.items():
        print(f"  {port}: {len(months)} months covered")
    if not table:
        print("  (no port reached the minimum coverage - table is empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
