"""Unit tests for single-use SSE stream tickets and access token separation (SEC-03 / ADR-02)."""

import pytest
from jose import jwt

from nexafreight.auth import (
    create_access_token,
    create_stream_ticket,
    decode_access_token,
    decode_stream_ticket,
    reset_stream_ticket_jtis,
)
from nexafreight.config import get_settings


@pytest.fixture(autouse=True)
def clean_consumed_jtis():
    reset_stream_ticket_jtis()
    yield
    reset_stream_ticket_jtis()


def test_stream_ticket_single_use():
    """Stream tickets can only be redeemed once (consume jti in TTL cache)."""
    settings = get_settings()
    ticket = create_stream_ticket(user_id="user-123", settings=settings, expires_in_seconds=60)

    # First decode: succeeds
    payload = decode_stream_ticket(ticket, settings=settings)
    assert payload["sub"] == "user-123"
    assert payload["scope"] == "stream_positions"
    assert "jti" in payload

    # Second decode with identical ticket: rejected as already used
    with pytest.raises(ValueError, match="Stream ticket has already been used"):
        decode_stream_ticket(ticket, settings=settings)


def test_access_token_rejected_as_stream_ticket():
    """Standard user session JWTs (access tokens) must be rejected if passed as stream tickets."""
    settings = get_settings()
    access_token = create_access_token(
        user_email="operator@nexafreight.dev",
        user_role="OPERATOR",
        settings=settings,
    )

    with pytest.raises(ValueError, match="Invalid ticket scope"):
        decode_stream_ticket(access_token, settings=settings)


def test_stream_ticket_rejected_as_access_token():
    """Stream tickets must never be accepted by decode_access_token."""
    settings = get_settings()
    ticket = create_stream_ticket(user_id="user-123", settings=settings, expires_in_seconds=60)

    with pytest.raises(ValueError, match="Stream tickets cannot be used as access tokens"):
        decode_access_token(ticket, settings=settings)
