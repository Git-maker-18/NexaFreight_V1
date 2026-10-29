"""Test that main.py lifespan never logs raw database_url with credentials."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from nexafreight.config import Settings
from nexafreight.main import create_app


@pytest.mark.asyncio
async def test_main_lifespan_does_not_log_database_credentials(capsys, caplog):
    """Assert main.py logs dialect and host only, never cleartext passwords, user info, or :// credentials."""
    secret_url = "postgresql+asyncpg://app_user:super_secret_password_123@db.neon.tech:5432/nexafreight_db"
    test_settings = Settings(
        database_url_override=secret_url,
        environment="test",
        jwt_secret="test-secret-key-for-unit-tests-only-min-32-chars",
        use_live_ais=False,
        enable_ais_listener=False,
        enable_position_interpolator=False,
        enable_disruption_detector=False,
        enable_sla_checker=False,
        enable_background_scheduler=False,
    )

    app = create_app(test_settings)

    with patch("nexafreight.main.create_engine") as mock_engine_factory:
        mock_engine = mock_engine_factory.return_value

        class AsyncBeginContext:
            async def __aenter__(self):
                class AsyncConn:
                    async def execute(self, *args, **kwargs):
                        return None
                return AsyncConn()

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        mock_engine.begin.return_value = AsyncBeginContext()

        with patch("nexafreight.main.refresh_parameters", new_callable=AsyncMock), \
             patch("nexafreight.main.dispose_engine", new_callable=AsyncMock):
            with caplog.at_level(logging.INFO):
                async with app.router.lifespan_context(app):
                    pass

    captured = capsys.readouterr().out
    combined_logs = captured + " " + " ".join([rec.message for rec in caplog.records])
    assert "super_secret_password_123" not in combined_logs
    assert "app_user" not in combined_logs
    assert "postgresql+asyncpg://" not in combined_logs
    assert "dialect=postgresql, host=db.neon.tech" in combined_logs


@pytest.mark.asyncio
async def test_main_lifespan_failure_does_not_leak_credentials(capsys, caplog):
    """Assert startup failure logs do not leak raw URLs or credentials."""
    secret_url = "postgresql+asyncpg://app_user:leaked_pass_456@db.neon.tech:5432/nexafreight_db"
    test_settings = Settings(
        database_url_override=secret_url,
        environment="test",
        jwt_secret="test-secret-key-for-unit-tests-only-min-32-chars",
        use_live_ais=False,
        enable_ais_listener=False,
        enable_position_interpolator=False,
        enable_disruption_detector=False,
        enable_sla_checker=False,
        enable_background_scheduler=False,
    )

    app = create_app(test_settings)

    with patch("nexafreight.main.create_engine") as mock_engine_factory:
        mock_engine = mock_engine_factory.return_value

        class FailingAsyncBegin:
            async def __aenter__(self):
                raise RuntimeError("connection refused with internal secret_url postgresql+asyncpg://app_user:leaked_pass_456@db.neon.tech:5432")

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        mock_engine.begin.return_value = FailingAsyncBegin()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as exc_info:
                async with app.router.lifespan_context(app):
                    pass

        assert "leaked_pass_456" not in str(exc_info.value)
        assert "app_user" not in str(exc_info.value)
        assert "postgresql+asyncpg://" not in str(exc_info.value)

    captured = capsys.readouterr().out
    combined_logs = captured + " " + " ".join([rec.message for rec in caplog.records])
    assert "leaked_pass_456" not in combined_logs
    assert "app_user" not in combined_logs
    assert "postgresql+asyncpg://" not in combined_logs
