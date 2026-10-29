"""Unit tests for nightly job runner session rollback on error (Item 7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.jobs.runner import run_nightly


@pytest.mark.asyncio
async def test_run_nightly_rollbacks_on_job_failure():
    """When a job raises an error, session.rollback() must be awaited and later jobs proceed."""
    mock_session = AsyncMock(spec=AsyncSession)

    # First job fails with exception, second job succeeds
    with (
        patch("nexafreight.jobs.runner.run_fx", side_effect=RuntimeError("DB Connection Error")),
        patch("nexafreight.jobs.runner.run_gdacs", new_callable=AsyncMock) as mock_gdacs,
        patch("nexafreight.jobs.runner.run_weather", new_callable=AsyncMock) as mock_weather,
    ):
        mock_gdacs.return_value = {"alerts": 5}
        mock_weather.return_value = {"updated": 10}

        report = await run_nightly(mock_session)

        # Confirm rollback was awaited on fx failure
        assert mock_session.rollback.await_count >= 1

        # Confirm report records error for fx but ok for others
        assert report["fx"]["status"] == "error"
        assert "DB Connection Error" in report["fx"]["detail"]
        assert report["gdacs"]["status"] == "ok"
        assert report["weather"]["status"] == "ok"

