"""Unit tests for POST /internal/nightly and jobs."""

import hashlib
import hmac
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from nexafreight.config import Settings
from nexafreight.models.external_event import ExternalEvent
from nexafreight.models.parameter import ParameterEmpirical
from sqlalchemy import select


def _auth(secret: str, ts: str | None = None) -> dict:
    stamp = ts or str(int(datetime.now(UTC).timestamp()))
    sig = hmac.new(secret.encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return {"X-Nexa-Timestamp": stamp, "X-Nexa-Signature": sig}


@pytest.fixture
def override_settings(test_app):
    """Provide a way to monkeypatch get_settings in the internal route."""
    def _override(nightly_secret_val: str | None):
        import nexafreight.api.routes.internal as route_module
        
        original = route_module.get_settings
        
        def mocked():
            return Settings(
                jwt_secret="testsecret",
                nightly_secret=nightly_secret_val
            )
            
        route_module.get_settings = mocked
        return original
        
    return _override


@pytest.mark.asyncio
async def test_nightly_503_when_secret_unset(client: AsyncClient, override_settings, monkeypatch) -> None:
    original = override_settings(None)
    try:
        response = await client.post("/internal/nightly")
        assert response.status_code == 503
        assert response.json() == {"detail": "nightly not configured"}
    finally:
        import nexafreight.api.routes.internal as route_module
        route_module.get_settings = original


@pytest.mark.asyncio
async def test_nightly_401_missing_headers(client: AsyncClient, override_settings, monkeypatch) -> None:
    original = override_settings("s3cret")
    try:
        response = await client.post("/internal/nightly")
        assert response.status_code == 401
        assert response.json() == {"detail": "missing auth headers"}
    finally:
        import nexafreight.api.routes.internal as route_module
        route_module.get_settings = original


@pytest.mark.asyncio
async def test_nightly_401_invalid_signature(client: AsyncClient, override_settings, monkeypatch) -> None:
    original = override_settings("s3cret")
    try:
        headers = _auth("wrongsecret")
        response = await client.post("/internal/nightly", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid signature"}
    finally:
        import nexafreight.api.routes.internal as route_module
        route_module.get_settings = original


@pytest.mark.asyncio
async def test_nightly_401_stale_timestamp(client: AsyncClient, override_settings, monkeypatch) -> None:
    original = override_settings("s3cret")
    try:
        stale_ts = str(int(datetime.now(UTC).timestamp()) - 3600)
        headers = _auth("s3cret", ts=stale_ts)
        response = await client.post("/internal/nightly", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "stale timestamp"}
    finally:
        import nexafreight.api.routes.internal as route_module
        route_module.get_settings = original


@pytest.mark.asyncio
async def test_nightly_200_runs_all_jobs_and_persists(client: AsyncClient, db_session, override_settings, monkeypatch) -> None:
    original = override_settings("s3cret")
    
    async def mock_get_json(url: str) -> dict:
        if "frankfurter" in url:
            return {"rates": {"INR": 87.42}, "date": "2026-09-26"}
        if "gdacs" in url:
            return {"features": [{"properties": {"eventid": 12345, "eventname": "Cyclone X", "alertlevel": "ORANGE", "eventtypecode": "TC", "fromdate": "2026-09-25T00:00:00Z"}, "geometry": {"coordinates": [85.0, 18.0]}}]}
        if "open-meteo" in url:
            return {"current": {"wind_speed_10m": 62.0, "precipitation": 2.0, "time": "2026-09-26T10:00:00Z"}}
        return {}

    monkeypatch.setattr("nexafreight.jobs.fx.get_json", mock_get_json)
    monkeypatch.setattr("nexafreight.jobs.gdacs.get_json", mock_get_json)
    monkeypatch.setattr("nexafreight.jobs.weather.get_json", mock_get_json)

    try:
        headers = _auth("s3cret")
        response = await client.post("/internal/nightly", headers=headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "ran_at" in data
        assert "report" in data
        
        report = data["report"]
        assert report["fx"]["status"] == "ok"
        assert report["gdacs"]["status"] == "ok"
        assert report["weather"]["status"] == "ok"
        
        fx_row = await db_session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd_inr"))
        fx_param = fx_row.scalar_one()
        assert fx_param.value == "87.4200"
        
        gdacs_events = (await db_session.execute(select(ExternalEvent).where(ExternalEvent.source == "GDACS"))).scalars().all()
        assert len(gdacs_events) == 1
        assert gdacs_events[0].severity == "ORANGE"
        
        meteo_events = (await db_session.execute(select(ExternalEvent).where(ExternalEvent.source == "OPEN-METEO"))).scalars().all()
        assert len(meteo_events) == 6
        assert meteo_events[0].severity == "ORANGE"
        
    finally:
        import nexafreight.api.routes.internal as route_module
        route_module.get_settings = original


@pytest.mark.asyncio
async def test_nightly_fx_upsert_idempotent(db_session, monkeypatch) -> None:
    async def mock_get_json(url: str) -> dict:
        return {"rates": {"INR": 87.42}, "date": "2026-09-26"}
    monkeypatch.setattr("nexafreight.jobs.fx.get_json", mock_get_json)
    
    from nexafreight.jobs.fx import run_fx
    
    await run_fx(db_session)
    await run_fx(db_session)
    
    fx_rows = (await db_session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd_inr"))).scalars().all()
    assert len(fx_rows) == 1
    assert fx_rows[0].sample_count == 2


@pytest.mark.asyncio
async def test_nightly_gdacs_skips_duplicates(db_session, monkeypatch) -> None:
    async def mock_get_json(url: str) -> dict:
        return {"features": [{"properties": {"eventid": 12345, "eventname": "Cyclone X", "alertlevel": "ORANGE", "eventtypecode": "TC", "fromdate": "2026-09-25T00:00:00Z"}, "geometry": {"coordinates": [85.0, 18.0]}}]}
    monkeypatch.setattr("nexafreight.jobs.gdacs.get_json", mock_get_json)
    
    from nexafreight.jobs.gdacs import run_gdacs
    
    await run_gdacs(db_session)
    await run_gdacs(db_session)
    
    events = (await db_session.execute(select(ExternalEvent).where(ExternalEvent.source == "GDACS"))).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_nightly_weather_below_threshold_stores_nothing(db_session, monkeypatch) -> None:
    async def mock_get_json(url: str) -> dict:
        return {"current": {"wind_speed_10m": 12.0, "precipitation": 0.0, "time": "2026-09-26T10:00:00Z"}}
    monkeypatch.setattr("nexafreight.jobs.weather.get_json", mock_get_json)
    
    from nexafreight.jobs.weather import run_weather
    
    summary = await run_weather(db_session)
    assert "0 breaches" in summary
    
    events = (await db_session.execute(select(ExternalEvent).where(ExternalEvent.source == "OPEN-METEO"))).scalars().all()
    assert len(events) == 0
