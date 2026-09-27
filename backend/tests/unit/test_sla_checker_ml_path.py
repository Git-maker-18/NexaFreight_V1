"""Regression test for audit finding E1 (Built_In_Errors_Audit.md).

sla_checker._predicted_p85 referenced LegStatus without importing it, so the
ML path raised NameError on every order; the function's broad except then
silently returned the planned arrival — the "ML rescore" never rescored
anything with ML.

This test stubs the ETA model and asserts the stub's prediction (not the
planned-arrival fallback) drives the returned P85 datetime. If anything in
the model path breaks again (missing import, signature drift), the fallback
wins and this test fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nexafreight.enums import LegStatus, ShipmentStatus
from nexafreight.services import sla_checker


class _StubPrediction:
    p10_eta_days = 1.25
    p50_eta_days = 2.25
    p85_eta_days = 3.25


@pytest.mark.asyncio
async def test_ml_path_actually_runs(db_session, make_shipment, make_order, make_leg):
    shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT)
    await make_leg(
        shipment.id,
        status=LegStatus.PLANNED,
        planned_departure=datetime.now(UTC) - timedelta(hours=6),
        planned_arrival=datetime.now(UTC) + timedelta(days=10),
    )
    order = await make_order(
        shipment=shipment,
        order_number="ORD-E1-REGRESSION",
        revenue=1000.0,
        shipping_cost=100.0,
    )
    await db_session.refresh(shipment, ["legs", "orders", "alerts", "origin", "destination"])
    await db_session.refresh(order, ["items"])

    stub_model = SimpleNamespace(predict=lambda features: _StubPrediction())
    with patch.object(sla_checker, "_get_eta_model", lambda: stub_model):
        p85 = sla_checker._predicted_p85(shipment, order, db_session)

    assert p85 is not None, "P85 must never be None when the model path is healthy"

    base_eta = sla_checker.latest_planned_arrival(shipment)
    assert base_eta is not None
    if base_eta.tzinfo is None:  # DB round-trip drops tz; normalize like prod guards do
        base_eta = base_eta.replace(tzinfo=UTC)
    expected_from_model = (order.order_date or datetime.now(UTC)) + timedelta(days=3.25)

    # The stub (3.25 days) must beat the 10-day planned arrival. Allow 2 min
    # of clock skew between order_date fallback and our reference 'now'.
    if order.order_date is not None:
        assert abs((p85 - expected_from_model).total_seconds()) < 120, (
            "P85 did not come from the stubbed model — the ML path is broken "
            "again and the planned-arrival fallback (the E1 regression) won."
        )
    else:
        assert p85 < base_eta - timedelta(days=1), (
            "P85 fell back to planned arrival — ML path broken (E1 regression)."
        )


@pytest.mark.asyncio
async def test_legstatus_is_imported():
    """Direct guard for the exact E1 defect: the module namespace must
    contain LegStatus (i.e., it was imported, not resolved via globals luck)."""
    assert "LegStatus" in dir(sla_checker)
