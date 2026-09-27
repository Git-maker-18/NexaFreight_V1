"""Nightly runner: executes all jobs; one job failing must not kill others."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.jobs.fx import run_fx
from nexafreight.jobs.gdacs import run_gdacs
from nexafreight.jobs.weather import run_weather

logger = structlog.get_logger(__name__)

async def run_nightly(session: AsyncSession) -> dict:
    """Run all nightly jobs and return a per-job report dict (JSON-safe)."""
    report: dict = {}
    
    for name, job in (("fx", run_fx), ("gdacs", run_gdacs), ("weather", run_weather)):
        try:
            detail = await job(session)
            report[name] = {"status": "ok", "detail": detail}
        except Exception as exc:  # noqa: BLE001 - report must always build
            logger.error("nightly_job_failed", job=name, error=str(exc))
            report[name] = {"status": "error", "detail": str(exc)[:300]}
            
    return report
