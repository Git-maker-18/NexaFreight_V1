"""Seed initial user accounts for development and testing.

Creates one or more user accounts for local development use.
Reads SEED_PASSWORD from environment, or generates a secure random password and prints it.
Safe to run multiple times (idempotent).

Usage:
    python scripts/seed_user.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.auth import hash_password
from nexafreight.config import get_settings
from nexafreight.database import get_session_factory
from nexafreight.enums import UserRole
from nexafreight.logging import configure_logging
from nexafreight.models.user import User

logger = logging.getLogger(__name__)


async def seed_users(session: AsyncSession) -> None:
    """Create initial user accounts if they don't already exist.

    Args:
        session: Database session
    """
    settings = get_settings()
    seed_pwd = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(16)

    # Define seed users
    seed_user_list = [
        {
            "email": "admin@nexafreight.local",
            "full_name": "System Administrator",
            "role": UserRole.ADMIN,
        },
        {
            "email": "operator@nexafreight.local",
            "full_name": "Operations Manager",
            "role": UserRole.OPERATOR,
        },
        {
            "email": "viewer@nexafreight.local",
            "full_name": "Dashboard Viewer",
            "role": UserRole.VIEWER,
        },
    ]

    for user_data in seed_user_list:
        # Check if user already exists
        result = await session.execute(select(User).where(User.email == user_data["email"]))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            logger.info(f"User already exists: {user_data['email']}")
            continue

        # Create new user
        hashed_password = hash_password(seed_pwd, settings)

        new_user = User(
            email=user_data["email"],
            hashed_password=hashed_password,
            full_name=user_data["full_name"],
            role=user_data["role"],
            is_active=True,
        )

        session.add(new_user)
        await session.flush()

        print(
            f"Seeded user: {user_data['email']} "
            f"(role={user_data['role'].value}, password={seed_pwd})"
        )

    await session.commit()
    logger.info("User seeding complete")


async def async_main() -> int:
    """Async entry point for seed script.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    settings = get_settings()
    configure_logging(settings)

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await seed_users(session)
            return 0
        except Exception as e:
            logger.error(f"User seeding failed: {e}")
            return 1


def main() -> int:
    """Synchronous entry point.

    Returns:
        Exit code
    """
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
