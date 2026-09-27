"""Unit tests: DATABASE_URL normalization for cloud Postgres (wave 1b)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from nexafreight.config import Settings


def _settings(override: str | None) -> Settings:
    return Settings(
        jwt_secret=SecretStr("x" * 40),
        database_url_override=override,
        database_path=Path("./data/unused.db"),
    )


def test_postgres_scheme_upgraded_to_asyncpg_with_param_set() -> None:
    url = _settings(
        "postgresql://neondb_owner:pw@ep-x-pooler.region.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    ).database_url
    assert url == (
        "postgresql+asyncpg://neondb_owner:pw@ep-x-pooler.region.aws.neon.tech/neondb"
        "?ssl=require"
    )


def test_bare_postgres_scheme_upgraded_without_query() -> None:
    url = _settings("postgres://user:pw@host.example:5432/db").database_url
    assert url == (
        "postgresql+asyncpg://user:pw@host.example:5432/db"
        "?ssl=require"
    )


def test_idempotent_existing_query_replaced_not_duplicated() -> None:
    raw = "postgresql://u:p@h/db?sslmode=require"
    once = _settings(raw).database_url
    assert once.count("ssl=") == 1
    assert "sslmode" not in once
    assert "statement_cache_size" not in once


def test_explicit_asyncpg_override_passthrough_unchanged() -> None:
    raw = "postgresql+asyncpg://nexa:nexa_password@localhost:5432/nexafreight"
    assert _settings(raw).database_url == raw


def test_sqlite_path_unchanged_when_no_override() -> None:
    settings = Settings(
        jwt_secret=SecretStr("x" * 40),
        database_url_override=None,
        database_path=Path("./data/nexa.db"),
    )
    assert settings.database_url == "sqlite+aiosqlite:///./data/nexa.db"
