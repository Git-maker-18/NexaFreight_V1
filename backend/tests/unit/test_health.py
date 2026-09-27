"""Tests for application health check endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "ok")

@pytest.mark.asyncio
async def test_healthz_check(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_readyz_check_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

@pytest.mark.asyncio
async def test_readyz_check_failure(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_get_engine():
        raise RuntimeError("DB down")

    monkeypatch.setattr("nexafreight.database.get_engine", mock_get_engine)
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
