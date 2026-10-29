"""Enforce append-only immutability on audit_logs via database triggers.

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-10-29 14:00:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is an append-only table: UPDATE and DELETE are prohibited';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_log_modification();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_log_modification();
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW
            BEGIN
                SELECT RAISE(FAIL, 'audit_logs is an append-only table: UPDATE and DELETE are prohibited');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW
            BEGIN
                SELECT RAISE(FAIL, 'audit_logs is an append-only table: UPDATE and DELETE are prohibited');
            END;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs;")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_modification();")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete;")
