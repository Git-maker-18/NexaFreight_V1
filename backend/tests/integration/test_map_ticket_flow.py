"""Integration test for /api/map/positions/stream-ticket and SSE single-use authentication."""

from __future__ import annotations

from unittest.mock import patch
import pytest
from httpx import AsyncClient

from nexafreight.auth import reset_stream_ticket_jtis
from nexafreight.models.user import User


@pytest.fixture(autouse=True)
def clean_jtis():
    reset_stream_ticket_jtis()
    yield
    reset_stream_ticket_jtis()


async def _mock_sse_generator(*args, **kwargs):
    yield "event: POSITION_UPDATE\ndata: []\n\n"


@pytest.mark.asyncio
async def test_map_stream_ticket_endpoint_and_single_use(
    client: AsyncClient,
    seed_operator_user: User,
    auth_headers: dict[str, str],
):
    # 1. Issue stream ticket with authenticated user session
    resp = await client.post(
        "/api/map/positions/stream-ticket",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "ticket" in data
    assert data["expires_in"] == 60
    ticket = data["ticket"]

    # 2. Use stream ticket to connect to /api/map/positions/stream
    # The ticket should be consumed on first connection
    with patch("nexafreight.api.routes.map._sse_generator", side_effect=_mock_sse_generator):
        sse_resp = await client.get(
            f"/api/map/positions/stream?ticket={ticket}",
        )
        assert sse_resp.status_code == 200
        assert "text/event-stream" in sse_resp.headers["content-type"]
        assert "event: POSITION_UPDATE" in sse_resp.text

        # 3. Replay with the same ticket must fail with 401 (single-use)
        replay_resp = await client.get(
            f"/api/map/positions/stream?ticket={ticket}",
        )
        assert replay_resp.status_code == 401

        # 4. Access token passed as ?ticket= must be rejected with 401
        access_token = auth_headers["Authorization"].split()[1]
        invalid_ticket_resp = await client.get(
            f"/api/map/positions/stream?ticket={access_token}",
        )
        assert invalid_ticket_resp.status_code == 401
