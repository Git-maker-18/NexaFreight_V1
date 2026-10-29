"""Integration test verifying audit_logs immutability triggers (SEC-09)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from nexafreight.models.audit import AuditLog


@pytest.mark.asyncio
async def test_audit_log_triggers_prevent_update_and_delete(db_session: AsyncSession):
    # Ensure SQLite triggers are active in the test session if SQLite (PostgreSQL triggers installed by Alembic)
    if db_session.bind.dialect.name == "sqlite":
        await db_session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW
            BEGIN
                SELECT RAISE(FAIL, 'audit_logs is an append-only table: UPDATE and DELETE are prohibited');
            END;
            """
        )
    )
        await db_session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
                BEFORE DELETE ON audit_logs
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(FAIL, 'audit_logs is an append-only table: UPDATE and DELETE are prohibited');
                END;
                """
            )
        )
        await db_session.commit()

    # 1. Insert must succeed
    entry = AuditLog(
        actor_type="system",
        actor_name="test_worker",
        action="test_action",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    entry_id = entry.id
    assert entry_id is not None

    # 2. Update must fail via trigger
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(f"UPDATE audit_logs SET action = 'tampered' WHERE id = {entry_id}")
        )
        await db_session.commit()
    await db_session.rollback()

    # 3. Delete must fail via trigger
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(f"DELETE FROM audit_logs WHERE id = {entry_id}")
        )
        await db_session.commit()
    await db_session.rollback()
