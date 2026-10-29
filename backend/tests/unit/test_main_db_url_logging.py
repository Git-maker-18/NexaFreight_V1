"""Test that main.py lifespan never logs raw database_url with credentials."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from nexafreight.config import Settings
from nexafreight.main import create_app


@pytest.mark.asyncio
async def test_main_lifespan_does_not_log_database_credentials(capsys):
    """Assert main.py logs dialect and host only, never cleartext passwords or full URLs."""
    secret_url = "postgresql+asyncpg://app_user:super_secret_password_123@db.neon.tech:5432/nexafreight_db"
    test_settings = Settings(
        database_url_override=secret_url,
        environment="test",
        jwt_secret="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        use_live_ais=False,
        enable_disruption_detector=False,
        enable_sla_checker=False,
        enable_scheduler=False,
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
            async with app.router.lifespan_context(app):
                pass

    captured = capsys.readouterr().out
    assert "super_secret_password_123" not in captured
    assert "app_user" not in captured
    assert "dialect=postgresql, host=db.neon.tech" in captured
