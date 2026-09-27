#!/usr/bin/env python3
"""Build cached real-path geometry for network edges (day-14).

ROAD edges: OpenRouteService directions (uses ORS_API_KEY from .env;
free tier is ~8,000 req/day and 40 req/min per ORS docs — the script
requests only edges WITHOUT geometry and sleeps 1.5 s between calls,
so re-runs are cheap). Profile: driving-hgv with automatic driving-car
fallback (OSM hgv tagging is sparse in India; some intercity hauls are
hgv-unroutable but car-routable).

RAIL edges: intentionally NOT filled by this script — the rail geometry
builder (OSM rail-graph extraction) is a follow-up patch; the column and
the dripper's precedence are already mode-agnostic, so rail geometry
lands without further code changes when its builder exists.

Exit codes: 0 ok/partial, 2 = cannot run (no key / DB unavailable) —
mirrors scripts/17's graceful semantics. Thin CLI wrapper over
nexafreight.services.land_geometry.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexafreight.database import get_session_factory  # noqa: E402
from nexafreight.services.land_geometry import fill_road_edge_geometries  # noqa: E402


async def main() -> int:
    factory = get_session_factory()
    async with factory() as session:
        stats = await fill_road_edge_geometries(session)
    if stats.get("no_key"):
        print("no PortDailyStat rows" if False else "no ORS API key configured (ORS_API_KEY) — nothing to do")
        return 2
    print(
        f"Edge geometry: filled={stats['filled']} failed={stats['failed']} "
        f"(ROAD edges only; rail builder is a follow-up patch)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
