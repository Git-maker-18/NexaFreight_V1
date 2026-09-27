"""Internal protected routes for nightly jobs (wave 2)."""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.config import get_settings
from nexafreight.database import get_db_session
from nexafreight.jobs.runner import run_nightly

router = APIRouter(tags=["internal"])

@router.post("/internal/nightly")
async def trigger_nightly(
    request: Request,
    x_nexa_timestamp: str | None = Header(default=None),
    x_nexa_signature: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Run all nightly jobs (HMAC-SHA256 protected)."""
    settings = get_settings()
    
    if settings.nightly_secret is None or not settings.nightly_secret.get_secret_value():
        return JSONResponse(status_code=503, content={"detail": "nightly not configured"})
        
    if x_nexa_timestamp is None or x_nexa_signature is None:
        return JSONResponse(status_code=401, content={"detail": "missing auth headers"})
        
    server_now = datetime.now(UTC)
    try:
        ts = int(x_nexa_timestamp)
        if abs(server_now.timestamp() - ts) > 300:
            return JSONResponse(status_code=401, content={"detail": "stale timestamp"})
    except ValueError:
        return JSONResponse(status_code=401, content={"detail": "stale timestamp"})
        
    secret_bytes = settings.nightly_secret.get_secret_value().encode("utf-8")
    expected = hmac.new(secret_bytes, x_nexa_timestamp.encode("ascii"), hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(expected, x_nexa_signature.strip().lower()):
        return JSONResponse(status_code=401, content={"detail": "invalid signature"})
        
    report = await run_nightly(session)
    
    from nexafreight.core.params import refresh_parameters
    await refresh_parameters(session)

    return JSONResponse(status_code=200, content={"ran_at": server_now.isoformat(), "report": report})
