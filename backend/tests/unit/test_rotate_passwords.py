"""Unit tests for scripts/rotate_passwords.py on SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.auth import hash_password, verify_password
from nexafreight.enums import UserRole
from nexafreight.models.user import User
from scripts.rotate_passwords import TARGET_EMAILS, rotate_passwords


@pytest.mark.asyncio
async def test_rotate_passwords_updates_target_accounts(db_session: AsyncSession):
    """rotate_passwords updates password hashes for standard accounts and returns account names."""
    old_hash = hash_password("OldPassword123!")

    # Seed the target accounts
    for email in TARGET_EMAILS:
        user = User(
            email=email,
            hashed_password=old_hash,
            full_name=f"User {email}",
            role=UserRole.ADMIN if "admin" in email else UserRole.OPERATOR,
            is_active=True,
        )
        db_session.add(user)
    await db_session.commit()

    # Verify old password
    for email in TARGET_EMAILS:
        u = (await db_session.execute(User.__table__.select().where(User.email == email))).mappings().one()
        assert verify_password("OldPassword123!", u["hashed_password"])

    # Rotate passwords
    new_password = "RotatedSecurePassword789!"
    updated = await rotate_passwords(db_session, new_password)

    # Assert exactly target accounts were updated and returned
    assert sorted(updated) == sorted(TARGET_EMAILS)

    # Verify each account now validates with new password and fails old password
    for email in TARGET_EMAILS:
        u = (await db_session.execute(User.__table__.select().where(User.email == email))).mappings().one()
        assert verify_password(new_password, u["hashed_password"])
        assert not verify_password("OldPassword123!", u["hashed_password"])

