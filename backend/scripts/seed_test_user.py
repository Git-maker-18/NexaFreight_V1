"""Seed one dev user. Run with: python scripts/seed_test_user.py"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select

from nexafreight.auth import hash_password
from nexafreight.database import get_session_factory
from nexafreight.enums import UserRole
from nexafreight.models.user import User


async def main() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == "operator@nexafreight.dev"))
        if result.scalar_one_or_none():
            print("Test user already exists.")
            return

        password = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(16)
        user = User(
            email="operator@nexafreight.dev",
            hashed_password=hash_password(password),
            role=UserRole.OPERATOR,
            full_name="Dev Operator",
        )
        session.add(user)
        await session.commit()
        print(f"Seeded operator@nexafreight.dev (password: {password})")


if __name__ == "__main__":
    asyncio.run(main())
