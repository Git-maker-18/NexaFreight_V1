"""Analytics tests (Definitive Plan — Phase 9): scorecard windows + rails."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.api.routes.analytics import ShipmentFinancialAggregate, window_stats


NOW = datetime.now(UTC)


def _agg(**kw):
    defaults = dict(
        shipment_id="s1",
        mode="SEA",
        status="IN_TRANSIT",
        revenue_usd=0.0,
        shipping_cost_usd=0.0,
        decided=False,
        realized_cost_usd=0.0,
        pending_sla_est_usd=0.0,
        pending_demurrage_est_usd=0.0,
        deadlines=[],
    )
    defaults.update(kw)
    return ShipmentFinancialAggregate(**defaults)


def test_window_stats_cumulative_membership() -> None:
    """Deadline at +12h appears in day, week AND month rollups."""
    close = _agg(
        revenue_usd=5_000.0,
        shipping_cost_usd=1_000.0,
        decided=True,
        realized_cost_usd=500.0,
        deadlines=[NOW + timedelta(hours=12)],
    )
    far = _agg(
        shipment_id="s2",
        revenue_usd=8_000.0,
        shipping_cost_usd=2_000.0,
        decided=False,
        pending_sla_est_usd=800.0,
        pending_demurrage_est_usd=250.0,
        deadlines=[NOW + timedelta(days=20)],
    )
    aggregates = [close, far]

    day = window_stats(aggregates, now=NOW, window_days=1.0)
    assert day.shipments == 1
    assert day.decided_margin == 3_500.0
    assert day.undecided_revenue == 0.0

    week = window_stats(aggregates, now=NOW, window_days=7.0)
    assert week.shipments == 1

    month = window_stats(aggregates, now=NOW, window_days=30.0)
    assert month.shipments == 2
    assert month.total_revenue == 13_000.0
    assert month.decided_margin == 3_500.0
    assert month.undecided_revenue == 8_000.0
    assert month.undecided_pending_sla_est == 800.0
    assert month.undecided_pending_demurrage_est == 250.0
    assert month.undecided_total_pending_est == 1_050.0


async def test_scorecard_endpoint_window_shape(
    client, seed_admin_user, auth_headers_factory, make_shipment, make_order, make_leg
) -> None:
    """Orders with near AND far deadlines roll up cumulatively."""
    headers = auth_headers_factory(seed_admin_user)

    s1 = await make_shipment(status="IN_TRANSIT", container_count=1)
    await make_leg(shipment_id=s1.id)
    await make_order(
        order_number="ORD-AN-CLOSE",
        shipment=s1,
        revenue=5_000.0,
        shipping_cost=1_000.0,
        sla_deadline=NOW + timedelta(hours=12),
    )
    s2 = await make_shipment(status="IN_TRANSIT", container_count=2)
    await make_leg(shipment_id=s2.id)
    await make_order(
        order_number="ORD-AN-FAR",
        shipment=s2,
        revenue=8_000.0,
        shipping_cost=2_000.0,
        sla_deadline=NOW + timedelta(days=20),
    )

    res = await client.get("/api/analytics/scorecard", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provenance"] == "DERIVED"

    # day ⊂ week ⊂ month
    assert body["day"]["shipments"] == 1
    assert body["week"]["shipments"] == 1
    assert body["month"]["shipments"] == 2
    assert body["month"]["total_revenue"] >= body["day"]["total_revenue"]

    # rows carry the P&L block per shipment
    assert len(body["rows"]) == 2
    for row in body["rows"]:
        for key in (
            "revenue_usd",
            "shipping_cost_usd",
            "total_costs_usd",
            "margin_usd",
            "margin_pct",
        ):
            assert key in row


async def test_scorecard_splits_by_provenance(
    client, seed_admin_user, auth_headers_factory, make_shipment, make_order, make_leg
) -> None:
    """E12: bake-era (DERIVED) and runtime (SIMULATED) roll up side by side."""
    from nexafreight.enums import Provenance

    headers = auth_headers_factory(seed_admin_user)

    s_runtime = await make_shipment(status="IN_TRANSIT", container_count=1)
    await make_leg(shipment_id=s_runtime.id)
    await make_order(
        order_number="ORD-PROV-RUN",
        shipment=s_runtime,
        revenue=5_000.0,
        shipping_cost=1_000.0,
        sla_deadline=NOW + timedelta(days=10),
    )
    s_bake = await make_shipment(
        status="IN_TRANSIT", container_count=1, provenance=Provenance.DERIVED
    )
    await make_leg(shipment_id=s_bake.id)
    await make_order(
        order_number="ORD-PROV-BAKE",
        shipment=s_bake,
        revenue=8_000.0,
        shipping_cost=2_000.0,
        sla_deadline=NOW + timedelta(days=10),
    )

    res = await client.get("/api/analytics/scorecard", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    by_prov = body.get("by_provenance", {})
    assert set(by_prov) == {"SIMULATED", "DERIVED"}
    assert by_prov["SIMULATED"]["shipments"] == 1
    assert by_prov["SIMULATED"]["revenue_usd"] == 5_000.0
    assert by_prov["DERIVED"]["shipments"] == 1
    assert by_prov["DERIVED"]["revenue_usd"] == 8_000.0


@pytest.mark.asyncio
async def test_financial_rows_pnl_math(
    client, seed_admin_user, auth_headers_factory, make_shipment, make_order, make_leg
) -> None:
    s = await make_shipment(status="IN_TRANSIT", container_count=2)
    await make_leg(shipment_id=s.id)
    await make_order(
        order_number="ORD-AN-PNL",
        shipment=s,
        revenue=10_000.0,
        shipping_cost=3_000.0,
        sla_deadline=NOW + timedelta(days=10),
    )
    headers = auth_headers_factory(seed_admin_user)
    res = await client.get("/api/analytics/scorecard", headers=headers)
    row = res.json()["rows"][0]
    assert row["revenue_usd"] == 10_000.0
    assert row["shipping_cost_usd"] == 3_000.0
    # margin + total costs == revenue
    assert row["margin_usd"] + row["total_costs_usd"] == pytest.approx(10_000.0)


async def test_sla_rail_reports_breach_and_exposure(
    client, seed_admin_user, auth_headers_factory, make_shipment, make_order, make_leg, db_session: AsyncSession
) -> None:
    from nexafreight.models import Disruption

    late = await make_shipment(status="IN_TRANSIT")
    await make_leg(
        shipment_id=late.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=11),
    )
    await make_order(
        order_number="ORD-AN-LATE",
        shipment=late,
        sla_deadline=NOW + timedelta(days=5),
    )
    disruption = Disruption(
        shipment_id=late.id,
        disruption_type="PORT_CONGESTION",
        status="ACTIVE",
        description="Slow customs at Rotterdam",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)

    ok_shipment = await make_shipment(status="IN_TRANSIT")
    await make_leg(
        shipment_id=ok_shipment.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=2),
    )
    await make_order(
        order_number="ORD-AN-OK",
        shipment=ok_shipment,
        sla_deadline=NOW + timedelta(days=6),
    )
    await db_session.commit()

    headers = auth_headers_factory(seed_admin_user)
    res = await client.get("/api/analytics/sla", headers=headers)
    assert res.status_code == 200
    rows = {r["shipment_id"]: r for r in res.json()["rows"]}

    late_row = rows[late.id]
    assert late_row["disrupted"] is True
    assert "Rotterdam" in (late_row["disruption_description"] or "")
    assert late_row["delay_days"] > 0

    ok_row = rows[ok_shipment.id]
    assert ok_row["disrupted"] is False
    assert ok_row["days_to_deadline"] is not None and ok_row["days_to_deadline"] >= 3


async def test_summary_counts_statuses_and_late_orders(
    client, db_session, seed_admin_user, auth_headers_factory, make_shipment, make_order, make_leg
) -> None:
    in_transit = await make_shipment(status="IN_TRANSIT")
    await make_leg(shipment_id=in_transit.id)
    delivered = await make_shipment(status="DELIVERED")
    late = await make_shipment(status="DELAYED")
    await make_leg(shipment_id=late.id)
    late_order = await make_order(
        order_number="ORD-AN-SUM", shipment=late, sla_deadline=NOW - timedelta(days=1)
    )
    late_order.sla_status = "LATE"
    await db_session.commit()

    headers = auth_headers_factory(seed_admin_user)
    res = await client.get("/api/analytics/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_shipments"] == 3
    assert body["in_transit"] == 1
    assert body["delivered"] == 1
    assert body["delayed"] == 1
    assert body["sla_breach_count"] >= 1
    assert body["summary_by_status"]["IN_TRANSIT"] == 1
    assert body["provenance"] == "DERIVED"
