"""Rotate passwords for default NexaFreight system accounts.

Reads DATABASE_URL and SEED_PASSWORD from the environment, updates hashed_password
for the standard operational accounts, and prints updated account names only.

Usage:
    export SEED_PASSWORD="your-strong-password"
    python scripts/rotate_passwords.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.auth import hash_password
from nexafreight.config import get_settings
from nexafreight.database import create_async_engine, create_session_factory
from nexafreight.models.user import User

TARGET_EMAILS = [
    "admin@nexafreight.local",
    "operator@nexafreight.local",
    "viewer@nexafreight.local",
    "operator@nexafreight.dev",
]


async def rotate_passwords(
    session: AsyncSession,
    seed_password: str,
    target_emails: list[str] | None = None,
) -> list[str]:
    """Update hashed_password for target accounts and return updated account names."""
    if not seed_password:
        raise ValueError("seed_password must be non-empty")

    emails = target_emails or TARGET_EMAILS
    new_hash = hash_password(seed_password)
    updated_accounts: list[str] = []

    for email in emails:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is not None:
            user.hashed_password = new_hash
            updated_accounts.append(user.email)

    await session.commit()
    return updated_accounts


async def main() -> None:
    seed_pwd = os.environ.get("SEED_PASSWORD")
    if not seed_pwd:
        print("ERROR: SEED_PASSWORD environment variable is required.", file=sys.stderr)
        sys.exit(1)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        settings = get_settings()
        db_url = settings.database_url

    engine = create_async_engine(db_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            updated = await rotate_passwords(session, seed_pwd)
            print(f"Password rotation complete. Updated {len(updated)} accounts:")
            for email in updated:
                print(f" - {email}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
