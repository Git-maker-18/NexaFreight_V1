"""Shared HTTP helper for nightly jobs (no external deps beyond httpx)."""
from __future__ import annotations

import structlog
import httpx

logger = structlog.get_logger(__name__)

_HTTP_TIMEOUT_S = 20.0

async def get_json(url: str) -> dict:
    """GET a JSON document with a hard timeout; raises on HTTP errors."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
