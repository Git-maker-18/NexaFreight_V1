#!/usr/bin/env python3
"""Seed the measured VIA_CAPE corridor (Task 20). Thin wrapper over
nexafreight.services.corridor_seed. Usage:
    JWT_SECRET=dev PYTHONPATH=src python scripts/23_seed_corridors.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nexafreight.database import get_session_factory  # noqa: E402
from nexafreight.services.corridor_seed import seed_corridors  # noqa: E402


async def main() -> int:
    factory = get_session_factory()
    async with factory() as session:
        lanes = await seed_corridors(session)
    print("VIA_CAPE seeded. Measured lanes (neo-panamax):")
    for name, m in lanes.items():
        print(
            f"  {name}: suez {m['suez_nm']:.0f} nm / {m['suez_h']:.1f} h -> "
            f"cape {m['cape_nm']:.0f} nm / {m['cape_h']:.1f} h "
            f"(x{m['distance_ratio']:.2f}, +{m['added_hours']:.1f} h)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
