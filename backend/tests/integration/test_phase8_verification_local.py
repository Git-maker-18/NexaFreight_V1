"""Test Phase 8 verification suite against the local production-mode FastAPI app."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from nexafreight.config import Settings
from nexafreight.main import create_app
from nexafreight.ml.registry import ModelRegistry


@pytest.mark.asyncio
async def test_all_phase8_checks_in_production(test_engine):
    """Verify that in production mode:
    1. /readyz and /healthz return 200
    2. /docs, /redoc, /openapi.json return 404
    3. Bad credentials rejected (401)
    4. Unauthenticated stream rejected (401)
    5. Predict ETA requires auth (401) and does not return 503
    """
    settings = Settings(
        environment="production",
        jwt_secret=SecretStr("super-secret-key-at-least-32-chars-long!"),
    )
    app = create_app(settings)
    app.state.ml_registry = ModelRegistry()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Probes
        r_readyz = await client.get("/readyz")
        assert r_readyz.status_code == 200

        r_healthz = await client.get("/healthz")
        assert r_healthz.status_code == 200

        # 2. Production docs return 404
        r_docs = await client.get("/docs")
        assert r_docs.status_code == 404

        r_redoc = await client.get("/redoc")
        assert r_redoc.status_code == 404

        r_openapi = await client.get("/openapi.json")
        assert r_openapi.status_code == 404

        # 3. Bad credentials rejected with 401
        r_login = await client.post(
            "/api/auth/login",
            json={"email": "operator@nexafreight.dev", "password": "wrong-unauthorized-password-123"},
        )
        assert r_login.status_code == 401

        # 4. Stream unauthenticated
        r_stream = await client.get("/api/map/positions/stream")
        assert r_stream.status_code == 401

        # 5. Predict ETA requires auth (401) and does NOT return 503
        r_eta = await client.post("/api/predict/eta", json={})
        assert r_eta.status_code == 401
