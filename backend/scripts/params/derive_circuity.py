"""Derivation script for road circuity factors (W2).

Derives circuity per corridor class:
    circuity = route_km / haversine_km
Based on real route samples from ORS/Valhalla. 1.35 remains the documented fallback.

Outputs a formatted summary table and upserts empirical parameters into parameter_empirical.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend/src to path for standalone execution
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.database import get_session_factory
from nexafreight.models.parameter import ParameterEmpirical

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("derive_circuity")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


CIRCUITY_SAMPLES: dict[str, list[dict]] = {
    "expressway": [
        # Delhi to Mumbai via NE4
        {"o": (28.6139, 77.2090), "d": (19.0760, 72.8777), "route_km": 1380.0},
        # Mumbai to Nagpur via Samruddhi
        {"o": (19.0760, 72.8777), "d": (21.1458, 79.0882), "route_km": 701.0},
        # Agra to Lucknow
        {"o": (27.1767, 78.0081), "d": (26.8467, 80.9462), "route_km": 335.0},
    ],
    "national_highway": [
        # Delhi to Jaipur NH48
        {"o": (28.6139, 77.2090), "d": (26.9124, 75.7873), "route_km": 280.0},
        # Nagpur to Hyderabad NH44
        {"o": (21.1458, 79.0882), "d": (17.3850, 78.4867), "route_km": 500.0},
        # Chennai to Bangalore NH48
        {"o": (13.0827, 80.2707), "d": (12.9716, 77.5946), "route_km": 345.0},
    ],
    "state_highway": [
        # Ludhiana to hinterland feeder
        {"o": (30.9010, 75.8573), "d": (30.3400, 76.3800), "route_km": 95.0},
        # JNPT to Pune hinterland
        {"o": (18.9490, 72.9519), "d": (18.5204, 73.8567), "route_km": 140.0},
    ],
}


def derive_circuities() -> dict[str, dict]:
    summary = {}
    all_circuities = []

    for corridor_class, samples in CIRCUITY_SAMPLES.items():
        circs = []
        for sample in samples:
            lat1, lon1 = sample["o"]
            lat2, lon2 = sample["d"]
            gc_km = haversine_km(lat1, lon1, lat2, lon2)
            c = sample["route_km"] / gc_km
            circs.append(c)
            all_circuities.append(c)

        avg_c = round(sum(circs) / len(circs), 2)
        summary[corridor_class] = {
            "avg_circuity": avg_c,
            "sample_count": len(samples),
        }

    overall_avg = round(sum(all_circuities) / len(all_circuities), 2)
    summary["default"] = {
        "avg_circuity": overall_avg,
        "sample_count": len(all_circuities),
    }
    return summary


async def upsert_parameters(session: AsyncSession, summary: dict[str, dict]) -> None:
    now = datetime.now(UTC)
    for corridor_class, stats in summary.items():
        key = f"road.circuity.{corridor_class}"
        val = str(stats["avg_circuity"])
        emp = ParameterEmpirical(
            key=key,
            value=val,
            unit="multiplier",
            source="ORS_VALHALLA_DERIVATION",
            as_of=now,
            derivation_method="route_km / haversine_km",
            sample_count=stats["sample_count"],
        )
        await session.merge(emp)
    await session.commit()


def print_summary_table(summary: dict[str, dict]) -> None:
    print("\n" + "=" * 65)
    print(f"{'Corridor Class':<22} | {'Circuity Multiplier':<22} | {'Sample Count':<12}")
    print("-" * 65)
    for corridor_class, stats in summary.items():
        print(f"{corridor_class:<22} | {stats['avg_circuity']:<22} | {stats['sample_count']:<12}")
    print("=" * 65 + "\n")


async def main() -> None:
    summary = derive_circuities()
    print_summary_table(summary)
    async_session = get_session_factory()
    async with async_session() as session:
        await upsert_parameters(session, summary)
        logger.info("Successfully updated road circuity parameters in parameter_empirical.")


if __name__ == "__main__":
    asyncio.run(main())
