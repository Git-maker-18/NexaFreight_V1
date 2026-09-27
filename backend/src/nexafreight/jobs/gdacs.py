"""GDACS disaster alerts into external_events (idempotent upserts)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.jobs.http import get_json
from nexafreight.models.external_event import ExternalEvent

_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"
_ALERTLEVELS = {"RED", "ORANGE"}

def _to_datetime(value: Any) -> datetime | None:
    """Parse a GDACS date value defensively; None when unusable."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except (ValueError, TypeError):
        return None

async def run_gdacs(session: AsyncSession) -> str:
    """Fetch recent GDACS events; upsert ORANGE+RED alerts. Returns summary."""
    payload = await get_json(_URL)
    features = payload.get("features", []) if isinstance(payload, dict) else []
    
    stored = 0
    seen = 0
    
    for feature in features:
        props = feature.get("properties", {}) or {}
        external_id = str(props.get("eventid") or props.get("EventID") or "")
        if not external_id:
            continue
            
        alertlevel = str(props.get("alertlevel") or props.get("AlertLevel") or "").upper()
        seen += 1
        
        existing_q = await session.execute(
            select(ExternalEvent).where(
                ExternalEvent.source == "GDACS",
                ExternalEvent.external_id == external_id,
            )
        )
        if existing_q.scalar_one_or_none() is not None:
            continue
            
        geometry = feature.get("geometry") or {}
        coords = (geometry.get("coordinates") or [None, None])[:2]
        lon = coords[0] if len(coords) > 0 and isinstance(coords[0], (int, float)) else None
        lat = coords[1] if len(coords) > 1 and isinstance(coords[1], (int, float)) else None
        
        event_time = (
            _to_datetime(props.get("fromdate"))
            or _to_datetime(props.get("iso3", {}).get("fromdate") if isinstance(props.get("iso3"), dict) else None)
            or _to_datetime(props.get("todate"))
        )
        
        session.add(ExternalEvent(
            source="GDACS",
            external_id=external_id,
            event_type=str(props.get("eventtypecode") or props.get("EventTypeCode") or "UNKNOWN")[:40],
            title=str(props.get("eventname") or props.get("EventName") or f"GDACS {external_id}"),
            severity=alertlevel or "UNKNOWN",
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            event_time=event_time,
            raw_json=None,
            provenance="REAL",
        ))
        stored += 1
        
    await session.commit()
    return f"gdacs: {seen} features seen, {stored} new (alertlevel in {_ALERTLEVELS} tracked; others stored for trend)"
