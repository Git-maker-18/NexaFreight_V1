"""Authentication endpoints."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.auth import create_access_token, verify_password
from nexafreight.config import Settings, get_settings
from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.exceptions import AuthenticationError, RateLimitExceededError
from nexafreight.models.user import User
from nexafreight.schemas.auth import LoginRequest, LoginResponse, UserOut, UserProfile

router = APIRouter()
logger = logging.getLogger(__name__)

# Dummy bcrypt hash used for timing attack / enumeration mitigation (constant-ish time verification)
_DUMMY_BCRYPT_HASH = "$2b$12$e80MvQkK7X.K/cQxK6Nqqu8w7E8eJgZ4k.V6fL4r7w8y9z0a1b2c3"

_AUTH_IP_TIMESTAMPS: dict[str, list[float]] = defaultdict(list)
_AUTH_EMAIL_TIMESTAMPS: dict[str, list[float]] = defaultdict(list)
AUTH_WINDOW_SECONDS = 60
AUTH_MAX_IP_ATTEMPTS = 30
AUTH_MAX_EMAIL_ATTEMPTS = 5


def get_client_ip(request: Request) -> str:
    """Extract client IP, inspecting X-Forwarded-For header behind reverse proxies (e.g. Render)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in X-Forwarded-For is the originating client
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def check_auth_rate_limit(key: str, storage: dict[str, list[float]], limit_type: str, max_attempts: int) -> None:
    now = time.time()
    cutoff = now - AUTH_WINDOW_SECONDS
    timestamps = [t for t in storage[key] if t > cutoff]
    if len(timestamps) >= max_attempts:
        retry_after = max(1, int(timestamps[0] + AUTH_WINDOW_SECONDS - now))
        raise RateLimitExceededError(
            message=f"Rate limit exceeded: too many login attempts for this {limit_type}. Please try again later.",
            retry_after=retry_after,
        )
    timestamps.append(now)
    storage[key] = timestamps


def reset_auth_rate_limits() -> None:
    """Reset rate limit caches (used in testing)."""
    _AUTH_IP_TIMESTAMPS.clear()
    _AUTH_EMAIL_TIMESTAMPS.clear()


@router.post("/login", response_model=LoginResponse, tags=["authentication"])
async def login(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """Authenticate user and issue JWT access token.

    Validates credentials against stored user record, ensuring:
    - Rate limits per IP and per email are enforced (429 with Retry-After)
    - Constant-time dummy verification for unknown users to prevent enumeration
    - Account is active

    On success, returns JWT access token and basic profile information.
    On failure, returns generic error without revealing existence of email.
    """
    client_ip = get_client_ip(request)
    email_key = credentials.email.lower().strip()

    check_auth_rate_limit(client_ip, _AUTH_IP_TIMESTAMPS, "IP address", max_attempts=AUTH_MAX_IP_ATTEMPTS)
    check_auth_rate_limit(email_key, _AUTH_EMAIL_TIMESTAMPS, "account", max_attempts=AUTH_MAX_EMAIL_ATTEMPTS)

    # Load user by email
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    # Generic error for non-existent user with dummy bcrypt check to mitigate timing attacks
    if not user:
        verify_password(credentials.password, _DUMMY_BCRYPT_HASH)
        logger.debug("Login attempt for non-existent account")
        raise AuthenticationError()

    # Verify password
    if not verify_password(credentials.password, user.hashed_password):
        logger.info(f"Login attempt with incorrect password: {credentials.email}")
        raise AuthenticationError()

    # Check account is active
    if not user.is_active:
        logger.info(f"Login attempt for inactive account: {credentials.email}")
        raise AuthenticationError("Account is inactive")

    # Create access token
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    access_token = create_access_token(
        user_email=user.email,
        user_role=role_str,
        settings=settings,
    )

    logger.info(f"Successful login: {user.email} (role={user.role})")

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserProfile(
            email=user.email,
            full_name=user.full_name,
            role=role_str,
            is_active=user.is_active,
        ),
        expires_in=settings.jwt_expiry_minutes * 60,  # Convert to seconds
    )


@router.get("/me", response_model=UserOut, tags=["authentication"])
async def get_me(
    user: User = Depends(get_current_user),
) -> User:
    """Return currently authenticated user profile."""
    return user
