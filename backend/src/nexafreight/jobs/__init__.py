"""Nightly ingestion jobs (wave 2): FX, GDACS alerts, Open-Meteo watch."""

from nexafreight.jobs.runner import run_nightly

__all__ = ["run_nightly"]
