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



@pytest.mark.asyncio
async def test_auth_forwarded_ips_limited_independently(client: AsyncClient):
    """Two different client IPs forwarded via proxy are tracked independently."""
    ip_a = "203.0.113.10"
    ip_b = "198.51.100.20"

    # Client A fails 10 login attempts across different emails
    for i in range(10):
        resp = await client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": f"{ip_a}, 10.0.0.1"},
            json={"email": f"victim_{i}@nexafreight.dev", "password": "wrong"},
        )
        assert resp.status_code == 401

    # Client B on a different IP should NOT be affected by Client A's traffic
    resp_b = await client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": f"{ip_b}, 10.0.0.1"},
        json={"email": "operator@nexafreight.dev", "password": "wrongpassword"},
    )
    assert resp_b.status_code == 401


@pytest.mark.asyncio
async def test_auth_ip_rate_limit_30_per_min(client: AsyncClient):
    """Exceeding 30 attempts from a single forwarded IP triggers HTTP 429."""
    ip = "192.0.2.55"
    for i in range(30):
        resp = await client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": ip},
            json={"email": f"unique_user_{i}@nexafreight.dev", "password": "wrong"},
        )
        assert resp.status_code == 401

    # 31st attempt from same IP must return 429
    resp_blocked = await client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": ip},
        json={"email": "another_user@nexafreight.dev", "password": "wrong"},
    )
    assert resp_blocked.status_code == 429
    assert "IP address" in resp_blocked.json()["error"]
