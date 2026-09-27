"""Regression test for audit finding E4 (Built_In_Errors_Audit.md).

Two demurrage models disagreed inside the same product:
  - alert_engine.estimate_demurrage billed with free_days = 4 (constant)
  - analytics._pending_exposure billed with free_days = 0 (hardcoded)
The same delay showed different money on the reroute screen vs the scorecard.

The fix: both call sites read ONE parameter (demurrage.free_days, default 4).
This test proves the parameter drives both surfaces identically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from nexafreight.core import params
from nexafreight.enums import LegStatus, ShipmentStatus
from nexafreight.services import alert_engine
from nexafreight.services.financial_engine import DEMURRAGE_DAILY_RATE
from nexafreight.api.routes import analytics


def _zero_free_days(key, default=None, **kwargs):
    if key == "demurrage.free_days":
        return 0
    if default is not None:
        return params.get_int(key, default, **kwargs)
    return params.get_int(key)


@pytest.mark.asyncio
async def test_free_days_param_drives_both_call_sites(db_session, make_shipment, make_order, make_leg):
    now = datetime.now(UTC)
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    # Planned arrival 5 days in the past → analytics "dwell" = (now - eta).days = 5
    await make_leg(
        shipment.id,
        status=LegStatus.PLANNED,
        planned_departure=now - timedelta(days=12),
        planned_arrival=now - timedelta(days=5),
    )
    await make_order(shipment=shipment, order_number="ORD-E4-001", revenue=5000.0, shipping_cost=500.0)
    await db_session.refresh(shipment, ["orders", "legs"])

    # Default (free_days=4): a 3-day delay bills nothing on the reroute surface
    assert alert_engine.estimate_demurrage(shipment, 72.0) == 0.0

    # Flip the single parameter to 0 → 5-day dwell bills on BOTH surfaces,
    # and both surfaces agree to the rupee (the E4 disagreement was 4-vs-0).
    with patch.object(params, "get_int", _zero_free_days):
        reroute_billed = alert_engine.estimate_demurrage(shipment, 120.0)  # 5-day delay
        assert reroute_billed > 0, "param flip must reach the reroute surface"

        _sla, dem_est, _realized = analytics._pending_exposure(shipment, now=now)
        assert dem_est > 0, "param flip must reach the analytics surface too"

    assert dem_est == pytest.approx(reroute_billed, rel=1e-6)


@pytest.mark.asyncio
async def test_default_free_days_consume_before_billing(db_session, make_shipment, make_order, make_leg):
    """Default behavior: 4 free days absorb short dwells — a 5-day-old ETA
    bills exactly 1 container-day (industry norm, not day-one billing)."""
    now = datetime.now(UTC)
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment.id,
        status=LegStatus.PLANNED,
        planned_departure=now - timedelta(days=12),
        planned_arrival=now - timedelta(days=5),
    )
    await make_order(shipment=shipment, order_number="ORD-E4-002", revenue=5000.0, shipping_cost=500.0)
    await db_session.refresh(shipment, ["orders", "legs"])

    _sla, dem_default, _realized = analytics._pending_exposure(shipment, now=now)
    assert dem_default == pytest.approx(DEMURRAGE_DAILY_RATE * max(1, shipment.container_count), rel=1e-6)

    # Same world viewed 3 days earlier: 2-day dwell sits inside free days → zero
    _sla2, dem_inside_free, _ = analytics._pending_exposure(shipment, now=now - timedelta(days=3))
    assert dem_inside_free == 0.0
