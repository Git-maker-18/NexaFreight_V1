"""Unit and endpoint tests for short-lived SSE stream tickets (SEC-03)."""

import pytest
from jose import jwt
from nexafreight.auth import create_stream_ticket, decode_stream_ticket
from nexafreight.config import get_settings


def test_create_and_decode_stream_ticket():
    settings = get_settings()
    user_id = 42

    ticket = create_stream_ticket(user_id=user_id, settings=settings, expires_in_seconds=60)
    assert isinstance(ticket, str)

    payload = decode_stream_ticket(ticket, settings=settings)
    assert payload["sub"] == "42"
    assert payload["scope"] == "stream_positions"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_stream_ticket_invalid_scope():
    settings = get_settings()
    # Issue a token with wrong scope
    bad_payload = {
        "sub": "42",
        "scope": "other_scope",
        "exp": 9999999999,
    }
    bad_ticket = jwt.encode(
        bad_payload,
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(ValueError, match="Invalid ticket scope"):
        decode_stream_ticket(bad_ticket, settings=settings)
