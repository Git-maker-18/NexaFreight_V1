import os
import pytest
from datetime import date
from sqlalchemy import select
from pathlib import Path

from nexafreight.models.location import Location
from nexafreight.models.port import Port, PortDailyStat
from nexafreight.models.base import Base
from sqlalchemy.ext.asyncio import create_async_engine

import importlib.util
spec = importlib.util.spec_from_file_location("ingest_port_data", "scripts/03_ingest_port_data.py")
ingest_port_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest_port_data)


@pytest.fixture
def activity_csv_path(tmp_path):
    csv_file = tmp_path / "activity.csv"
    csv_file.write_text(
        "date,portname,portcalls\n"
        "2024-01-01,Nhava Sheva,10\n"
        "2024-01-02,Nhava Sheva,12\n"
        "2024-01-03,Kolkata,5\n"
        "2024-01-01,UnknownPort,100\n"
        "2023-12-31,Nhava Sheva,9\n"
        "2024-01-04,Nhava Sheva,15\n"
    )
    return str(csv_file)


@pytest.fixture
async def temp_db_url(tmp_path):
    db_file = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db_url
    await engine.dispose()


@pytest.mark.asyncio
async def test_port_stats_ingestion_and_alias_matching(temp_db_url, activity_csv_path, monkeypatch):
    monkeypatch.setattr(ingest_port_data, "get_db_url", lambda: temp_db_url)
    
    # Setup 2 location rows
    engine = create_async_engine(temp_db_url)
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as session:
        loc1 = Location(locode="INJNP", name="Jawaharlal Nehru", country_code="IN", location_type="PORT", lat=18.9, lon=72.9)
        loc2 = Location(locode="INCCU", name="Calcutta", country_code="IN", location_type="PORT", lat=22.5, lon=88.3)
        session.add_all([loc1, loc2])
        await session.commit()
    
    # Run the loader with the mocked CSV
    args = ingest_port_data.parse_args([
        "--activity", activity_csv_path,
        "--start", "2024-01-01",
        "--end", "2024-01-05"
    ])
    
    res = await ingest_port_data.amain(args)
    assert res == 0
    
    async with AsyncSession(engine) as session:
        # Verify rows landed and source-tag is CALIBRATED
        stats = (await session.execute(
            select(PortDailyStat)
            .join(Port, Port.id == PortDailyStat.port_id)
            .join(Location, Location.id == Port.location_id)
        )).scalars().all()
        
        assert len(stats) == 4
        
        for s in stats:
            assert s.source == "CALIBRATED"
            assert s.congestion_index > 0
        
        stat_dates = sorted([s.stat_date for s in stats])
        assert stat_dates == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_port_stats_ingestion_limit_and_window(temp_db_url, activity_csv_path, monkeypatch):
    monkeypatch.setattr(ingest_port_data, "get_db_url", lambda: temp_db_url)
    
    engine = create_async_engine(temp_db_url)
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(engine) as session:
        # Setup 2 location rows
        loc1 = Location(locode="INJNP", name="Jawaharlal Nehru", country_code="IN", location_type="PORT", lat=18.9, lon=72.9)
        loc2 = Location(locode="INCCU", name="Calcutta", country_code="IN", location_type="PORT", lat=22.5, lon=88.3)
        session.add_all([loc1, loc2])
        await session.commit()
    
    # Run loader with limit=2
    args = ingest_port_data.parse_args([
        "--activity", activity_csv_path,
        "--start", "2024-01-01",
        "--limit", "2"
    ])
    
    res = await ingest_port_data.amain(args)
    assert res == 0
    
    async with AsyncSession(engine) as session:
        stats = (await session.execute(select(PortDailyStat))).scalars().all()
        assert len(stats) == 2
    await engine.dispose()
