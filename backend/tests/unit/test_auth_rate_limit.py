"""Unit tests for authentication rate limiting and timing-attack mitigation (Item 21)."""

from __future__ import annotations

import logging
from unittest.mock import patch
import pytest
from httpx import AsyncClient

from nexafreight.api.routes.auth import reset_auth_rate_limits
from nexafreight.models.user import User


@pytest.fixture(autouse=True)
def clean_auth_limits():
    reset_auth_rate_limits()
    yield
    reset_auth_rate_limits()


@pytest.mark.asyncio
async def test_auth_dummy_bcrypt_and_log_level(client: AsyncClient, caplog: pytest.LogCaptureFixture):
    """Unknown user login invokes dummy bcrypt check and does not log unknown email at INFO."""
    with patch("nexafreight.api.routes.auth.verify_password", return_value=False) as mock_verify:
        with caplog.at_level(logging.INFO):
            resp = await client.post(
                "/api/auth/login",
                json={"email": "nonexistent_victim@nexafreight.dev", "password": "wrongpassword1"},
            )
            assert resp.status_code == 401
            assert mock_verify.called

            # Check caplog at INFO level does NOT leak or log the email
            info_logs = [record.message for record in caplog.records if record.levelno >= logging.INFO]
            assert not any("nonexistent_victim@nexafreight.dev" in log for log in info_logs)


@pytest.mark.asyncio
async def test_auth_rate_limit_exceeded_returns_429(client: AsyncClient):
    """Exceeding max attempts triggers HTTP 429 with Retry-After header."""
    email = "target_account@nexafreight.dev"
    for i in range(5):
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": f"attempt{i}"},
        )
        assert resp.status_code == 401

    # 6th attempt within window must be rate limited (429)
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "sixth_attempt"},
    )
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0
    assert "Rate limit exceeded" in resp.json()["error"]

