import uuid
from typing import Any
import logging
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from nexafreight.config import Settings, get_settings

logger = logging.getLogger(__name__)

_CONSUMED_STREAM_JTIS: dict[str, float] = {}


def consume_stream_ticket_jti(jti: str, exp: float) -> bool:
    """Consume a ticket JTI in an in-memory TTL cache.
    Returns True if successfully consumed, False if already consumed or expired.
    """
    now_ts = datetime.now(UTC).timestamp()
    expired = [k for k, v in _CONSUMED_STREAM_JTIS.items() if v < now_ts]
    for k in expired:
        _CONSUMED_STREAM_JTIS.pop(k, None)
    if jti in _CONSUMED_STREAM_JTIS:
        return False
    _CONSUMED_STREAM_JTIS[jti] = exp
    return True


def reset_stream_ticket_jtis() -> None:
    """Clear consumed JTIs cache (used for test teardown)."""
    _CONSUMED_STREAM_JTIS.clear()


class TokenPayload(BaseModel):
    """Structured JWT token payload.

    Ensures type safety when encoding/decoding tokens, avoiding
    passing raw dicts throughout the codebase.
    """

    sub: str  # Subject (user email)
    role: str  # User role
    exp: int  # Expiration timestamp
    iat: int  # Issued-at timestamp


def hash_password(password: str, settings: Settings | None = None) -> str:
    """Hash a plaintext password using bcrypt.

    Uses the bcrypt work factor from settings to ensure consistent
    security posture across environments.

    Args:
        password: Plaintext password to hash
        settings: Application settings containing bcrypt_rounds

    Returns:
        Hashed password string suitable for storage
    """
    if settings is None:
        settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        password: Plaintext password to verify
        hashed_password: Stored bcrypt hash

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as e:
        logger.warning(f"Password verification failed with exception: {e}")
        return False


def create_access_token(
    user_email: str,
    user_role: str,
    settings: Settings | None = None,
) -> str:
    """Create a signed JWT access token for a user.

    Encodes user identity (email), role, and standard JWT claims
    (iat, exp) using the algorithm and secret from settings.

    Args:
        user_email: User's email (becomes 'sub' claim)
        user_role: User's role for authorization checks
        settings: Application settings containing JWT config

    Returns:
        Signed JWT token string
    """
    if settings is None:
        settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.jwt_expiry_minutes)

    payload = TokenPayload(
        sub=user_email,
        role=user_role,
        exp=int(expires.timestamp()),
        iat=int(now.timestamp()),
    )

    token = jwt.encode(
        payload.model_dump(),
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return token


def decode_access_token(token: str, settings: Settings | None = None) -> TokenPayload:
    """Decode and verify a JWT access token.

    Args:
        token: JWT token string
        settings: Application settings containing JWT config

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid, expired, or malformed
        ValueError: If token missing required claims
    """
    if settings is None:
        settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        logger.warning(f"JWT decode failed: {e}")
        raise

    # Validate required claims
    if payload.get("scope") == "stream_positions":
        raise ValueError("Stream tickets cannot be used as access tokens")
    if "sub" not in payload:
        raise ValueError("Token missing 'sub' claim")
    if "role" not in payload:
        raise ValueError("Token missing 'role' claim")
    if "exp" not in payload:
        raise ValueError("Token missing 'exp' claim")

    return TokenPayload(**payload)


def create_stream_ticket(
    user_id: int | str,
    settings: Settings | None = None,
    expires_in_seconds: int = 60,
) -> str:
    """Create a short-lived (60s) single-scope ticket for SSE stream authentication."""
    if settings is None:
        settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=expires_in_seconds)

    payload = {
        "sub": str(user_id),
        "scope": "stream_positions",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_stream_ticket(
    ticket: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode, verify, and consume a single-use SSE stream ticket.

    Raises:
        JWTError: If ticket is invalid, expired, or malformed
        ValueError: If ticket missing required claims, scope is not stream_positions, or ticket already used
    """
    if settings is None:
        settings = get_settings()
    payload = jwt.decode(
        ticket,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("scope") != "stream_positions":
        raise ValueError("Invalid ticket scope")
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or exp is None:
        raise ValueError("Stream ticket missing jti or exp claim")
    if not consume_stream_ticket_jti(jti, float(exp)):
        raise ValueError("Stream ticket has already been used")
    return payload
