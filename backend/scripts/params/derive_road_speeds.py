"""Derivation script for road speeds with halt allowances (W2).

Derives effective truck speeds per corridor class:
    effective = route_km / (engine_duration + halt_allowance)
where halt_allowance = (engine_duration / 4.5) * 0.75h (checkpost / toll / rest).

Outputs a formatted summary table and upserts empirical parameters into parameter_empirical.
"""

from __future__ import annotations

import asyncio
import logging
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
logger = logging.getLogger("derive_road_speeds")

CORRIDOR_SAMPLES: dict[str, list[dict]] = {
    "expressway": [
        {"name": "Delhi - Mumbai Expressway (NE4)", "route_km": 1380.0, "engine_h": 16.0},
        {"name": "Mumbai - Nagpur Samruddhi Mahamarg", "route_km": 701.0, "engine_h": 8.5},
        {"name": "Yamuna Expressway + Agra-Lucknow", "route_km": 467.0, "engine_h": 5.8},
    ],
    "national_highway": [
        {"name": "NH48 Delhi - Jaipur", "route_km": 280.0, "engine_h": 4.6},
        {"name": "NH44 Nagpur - Hyderabad", "route_km": 500.0, "engine_h": 8.2},
        {"name": "NH16 Chennai - Vizag", "route_km": 800.0, "engine_h": 13.5},
    ],
    "state_highway": [
        {"name": "SH Feeder Punjab (Ludhiana hinterland)", "route_km": 150.0, "engine_h": 3.2},
        {"name": "SH Feeder Maharashtra (JNPT hinterland)", "route_km": 180.0, "engine_h": 3.9},
    ],
}


def compute_halt_allowance(engine_h: float) -> float:
    """Halt allowance: ~0.75h per 4.5h driving (checkpost/toll/driver rest)."""
    return (engine_h / 4.5) * 0.75


def derive_speeds() -> dict[str, dict]:
    summary = {}
    all_effective = []

    for corridor_class, samples in CORRIDOR_SAMPLES.items():
        effective_speeds = []
        for sample in samples:
            dist_km = sample["route_km"]
            eng_h = sample["engine_h"]
            halt_h = compute_halt_allowance(eng_h)
            total_h = eng_h + halt_h
            eff_speed = dist_km / total_h
            effective_speeds.append(eff_speed)
            all_effective.append(eff_speed)

        avg_speed = round(sum(effective_speeds) / len(effective_speeds), 1)
        summary[corridor_class] = {
            "avg_speed_kmh": avg_speed,
            "sample_count": len(samples),
        }

    overall_avg = round(sum(all_effective) / len(all_effective), 1)
    summary["default"] = {
        "avg_speed_kmh": overall_avg,
        "sample_count": len(all_effective),
    }
    return summary


async def upsert_parameters(session: AsyncSession, summary: dict[str, dict]) -> None:
    now = datetime.now(UTC)
    for corridor_class, stats in summary.items():
        key = f"road.speed.{corridor_class}"
        val = str(stats["avg_speed_kmh"])
        emp = ParameterEmpirical(
            key=key,
            value=val,
            unit="km/h",
            source="ORS_DERIVATION",
            as_of=now,
            derivation_method="route_km / (engine_duration + halt_allowance)",
            sample_count=stats["sample_count"],
        )
        await session.merge(emp)
    await session.commit()


def print_summary_table(summary: dict[str, dict]) -> None:
    print("\n" + "=" * 65)
    print(f"{'Corridor Class':<22} | {'Effective Speed (km/h)':<22} | {'Sample Count':<12}")
    print("-" * 65)
    for corridor_class, stats in summary.items():
        print(f"{corridor_class:<22} | {stats['avg_speed_kmh']:<22} | {stats['sample_count']:<12}")
    print("=" * 65 + "\n")


async def main() -> None:
    summary = derive_speeds()
    print_summary_table(summary)
    async_session = get_session_factory()
    async with async_session() as session:
        await upsert_parameters(session, summary)
        logger.info("Successfully updated road speed parameters in parameter_empirical.")


if __name__ == "__main__":
    asyncio.run(main())
