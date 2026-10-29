"""Unit tests asserting /docs, /redoc, and /openapi.json return 404 in production."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from nexafreight.config import Settings
from nexafreight.main import create_app


@pytest.mark.asyncio
async def test_production_disables_api_docs():
    """In production environment, documentation routes must return 404."""
    prod_settings = Settings(
        environment="production",
        jwt_secret=SecretStr("super-secret-key-that-is-at-least-32-bytes-long!"),
        database_url_override="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(prod_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_docs = await client.get("/docs")
        assert r_docs.status_code == 404

        r_redoc = await client.get("/redoc")
        assert r_redoc.status_code == 404

        r_openapi = await client.get("/openapi.json")
        assert r_openapi.status_code == 404


@pytest.mark.asyncio
async def test_development_enables_api_docs():
    """In development environment, documentation routes must return 200."""
    dev_settings = Settings(
        environment="development",
        jwt_secret=SecretStr("super-secret-key-that-is-at-least-32-bytes-long!"),
        database_url_override="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(dev_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_docs = await client.get("/docs")
        assert r_docs.status_code == 200

        r_redoc = await client.get("/redoc")
        assert r_redoc.status_code == 200

        r_openapi = await client.get("/openapi.json")
        assert r_openapi.status_code == 200

