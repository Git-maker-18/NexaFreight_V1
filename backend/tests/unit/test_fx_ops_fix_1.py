import pytest
from sqlalchemy import select
from datetime import UTC, datetime
from nexafreight.models.parameter import ParameterEmpirical
from nexafreight.core import params
from nexafreight.jobs.fx import run_fx
from nexafreight.services.alert_engine import estimate_demurrage

@pytest.mark.asyncio
async def test_t1_and_t2(db_session, monkeypatch):
    # T1: store ParameterEmpirical("fx.usd_inr", "95.82") -> refresh -> params.get_float("fx.usd_inr") == 95.82
    db_session.add(ParameterEmpirical(
        key="fx.usd_inr", value="95.82", source="T1", unit="INR per USD", sample_count=1, as_of=datetime.now(UTC), derivation_method="Test"
    ))
    await db_session.commit()
    
    await params.refresh_parameters(db_session)
    assert params.get_float("fx.usd_inr") == 95.82

    # T2: after updating the row value and re-refreshing, get_float returns the new value
    row = (await db_session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd_inr"))).scalar_one()
    row.value = "96.00"
    await db_session.commit()
    
    await params.refresh_parameters(db_session)
    assert params.get_float("fx.usd_inr") == 96.00

@pytest.mark.asyncio
async def test_t3_fx_job_upsert(db_session, monkeypatch):
    # Seed legacy
    db_session.add(ParameterEmpirical(
        key="fx.usd.inr", value="80.0", source="Legacy", unit="INR per USD", sample_count=1, as_of=datetime.now(UTC), derivation_method="Test"
    ))
    # Seed existing
    db_session.add(ParameterEmpirical(
        key="fx.usd_inr", value="85.0", source="Existing", unit="INR per USD", sample_count=1, as_of=datetime.now(UTC), derivation_method="Test"
    ))
    await db_session.commit()
    
    async def mock_get_json(url: str) -> dict:
        return {"rates": {"INR": 95.82}, "date": "2026-09-27"}
    monkeypatch.setattr("nexafreight.jobs.fx.get_json", mock_get_json)
    
    await run_fx(db_session)
    
    # Assert existing row updated
    row = (await db_session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd_inr"))).scalar_one()
    assert row.value == "95.8200"
    assert row.sample_count == 2
    
    # Assert legacy deleted
    legacy = (await db_session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd.inr"))).scalar_one_or_none()
    assert legacy is None

@pytest.mark.asyncio
async def test_t4_alert_path(db_session, monkeypatch):
    # T4: alert path: demurrage computation consumes the live rate
    db_session.add(ParameterEmpirical(
        key="fx.usd_inr", value="100.0", source="T4", unit="INR per USD", sample_count=1, as_of=datetime.now(UTC), derivation_method="Test"
    ))
    await db_session.commit()
    await params.refresh_parameters(db_session)
    
    class _Sh:
        container_count = 2

    # 5 days -> 1 billable day. Rate = 5500 / 100 = 55/box. 2 boxes = 110.
    val = estimate_demurrage(_Sh(), 24.0 * 5)
    assert val == 110.0
