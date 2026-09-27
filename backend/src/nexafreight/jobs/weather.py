"""Open-Meteo port-weather watch: store only threshold breaches."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.jobs.http import get_json
from nexafreight.models.external_event import ExternalEvent

# The six Indian SEA ports from the network seed (locode -> lat, lon)
_PORTS: dict[str, tuple[float, float]] = {
    "INJNP": (18.9490, 72.9519),
    "INMUN": (22.7402, 69.7066),
    "INMAA": (13.0825, 80.2867),
    "INVTZ": (17.6868, 83.2185),
    "INCCU": (22.5726, 88.3639),
    "INCOK": (9.9312, 76.2673),
}

_WIND_ALERT_KMH = 50.0   # roughly Beaufort 7+; disrupts crane ops
_RAIN_ALERT_MM = 50.0    # heavy shower band; flooding risk at ports

async def run_weather(session: AsyncSession) -> str:
    """Check current wind/rain at the six ports; record breaches. Returns summary."""
    breaches = 0
    checked = 0
    today = datetime.now(UTC).date().isoformat()
    
    for locode, (lat, lon) in _PORTS.items():
        payload = await get_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current=wind_speed_10m,precipitation"
        )
        current = payload.get("current", {})
        wind = current.get("wind_speed_10m")
        rain = current.get("precipitation")
        
        if wind is None and rain is None:
            continue
            
        checked += 1
        wind = float(wind) if wind is not None else 0.0
        rain = float(rain) if rain is not None else 0.0
        
        if wind < _WIND_ALERT_KMH and rain < _RAIN_ALERT_MM:
            continue
            
        external_id = f"weather-{locode}-{today}"
        existing_q = await session.execute(
            select(ExternalEvent).where(
                ExternalEvent.source == "OPEN-METEO",
                ExternalEvent.external_id == external_id,
            )
        )
        if existing_q.scalar_one_or_none() is not None:
            continue
            
        severity = "RED" if wind >= 70.0 or rain >= 100.0 else "ORANGE"
        
        session.add(ExternalEvent(
            source="OPEN-METEO",
            external_id=external_id,
            event_type="WEATHER",
            title=f"{locode}: wind {wind:.0f} km/h, rain {rain:.1f} mm",
            severity=severity,
            latitude=lat,
            longitude=lon,
            event_time=datetime.now(UTC),
            raw_json=None,
            provenance="REAL",
        ))
        breaches += 1
        
    await session.commit()
    return f"open-meteo: {checked} ports checked, {breaches} breaches stored"
