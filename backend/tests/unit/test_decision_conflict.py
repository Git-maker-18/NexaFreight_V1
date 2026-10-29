"""Unit tests for decision execution conflict handling (Items 8, 23)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.exc import IntegrityError

from nexafreight.enums import DecisionAction
from nexafreight.exceptions import ConflictError
from nexafreight.models.user import User
from nexafreight.services.decision_executor import execute_decision


@pytest.mark.asyncio
async def test_execute_decision_catches_integrity_error_and_raises_conflict():
    """Concurrent approval triggering DB IntegrityError must raise ConflictError (HTTP 409)."""
    mock_session = AsyncMock()
    mock_alert = MagicMock()
    mock_alert.id = "alt-1"
    mock_alert.shipment_id = "shp-1"
    mock_alert.disruption_id = "dis-1"

    mock_shipment = MagicMock()
    mock_shipment.id = "shp-1"
    mock_shipment.route_version = 1

    mock_user = MagicMock(spec=User)
    mock_user.id = "usr-1"
    mock_user.full_name = "Test Operator"

    mock_option = MagicMock()
    mock_option.option_key = "accept_delay"
    mock_option.action = DecisionAction.ACCEPT_DELAY
    mock_option.total_impact_usd = 100.0
    mock_option.to_dict.return_value = {"option_key": "accept_delay"}

    # Mock DB query results
    mock_session.get.side_effect = lambda model, ident: {
        "alt-1": mock_alert,
        "shp-1": mock_shipment,
        "dis-1": MagicMock(),
    }.get(ident)

    # First scalar_one_or_none returns None (no existing decision at query time)
    mock_exec_result = MagicMock()
    mock_exec_result.scalar_one_or_none.return_value = None
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_exec_result

    # On flush, simulate unique constraint violation from concurrent commit
    mock_session.flush.side_effect = IntegrityError("UNIQUE constraint failed: decisions.alert_id", params={}, orig=Exception())

    with patch("nexafreight.services.decision_executor.generate_options", return_value=[mock_option]):
        with pytest.raises(ConflictError, match="already has a decision"):
            await execute_decision(
                session=mock_session,
                alert_id="alt-1",
                option_key="accept_delay",
                user=mock_user,
            )

        # Confirm rollback was invoked
        assert mock_session.rollback.called

