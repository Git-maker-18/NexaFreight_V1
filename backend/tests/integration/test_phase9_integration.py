"""End-to-end integration: full disruption→alert→decision loop (Plan §Phase 11).

  POST /disruptions          (manual report — feeds the pipeline)
  → GET /alerts              (alert raised with financial exposure)
  → PATCH /alerts/{id}/acknowledge
  → GET /alerts/{id}/options (exactly 3 scored options)
  → POST /alerts/{id}/approve (executes the decision, rewrites legs)
  → GET /decisions           (paper trail)
  → audit logs record the action
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.database import create_session_factory
from nexafreight.enums import AlertStatus, ShipmentStatus
from nexafreight.models import AuditLog, CorridorAlternative, Leg


NOW = datetime.now(UTC)


async def test_remaining_definitive_flow(
    client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
    seed_admin_user,
    seed_operator_user,
    auth_headers_factory,
    make_shipment,
    make_order,
    make_leg,
    make_location,
) -> None:
    # --- world: shipment mid-sea, tight SLA, corridor alternative seeded ---
    rotterdam = await make_location(
        locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.9225, longitude=4.479
    )
    shipment = await make_shipment(
        status=ShipmentStatus.IN_TRANSIT,
        destination=rotterdam,
        container_count=2,
        route_version=1,
    )
    leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        status="PLANNED",
        destination=rotterdam,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=10, hours=6),
    )
    leg.distance_km = 5_000.0
    await db_session.commit()

    await make_order(
        order_number="ORD-FLOW-1",
        shipment=shipment,
        revenue=50_000.0,
        shipping_cost=3_000.0,
        sla_deadline=NOW + timedelta(hours=20),  # breach lands at +36h delay
    )
    corridor = CorridorAlternative(
        option_key="VIA_PIRAEUS",
        display_name="Divert via Piraeus",
        applicable_disruption_types_json=json.dumps(["PORT_CONGESTION"]),
        route_template_json=json.dumps({"legs": [{"mode": "SEA", "to": "DESTINATION"}]}),
        cost_delta_factor=1.2,
        time_delta_hours=30.0,
        co2_delta_factor=1.1,
    )
    db_session.add(corridor)
    await db_session.commit()

    headers = auth_headers_factory(seed_admin_user)

    # --- 1. report a disruption → auto-assessed, alert raised ---
    res = await client.post(
        "/api/disruptions",
        json={
            "shipment_id": shipment.id,
            "disruption_type": "PORT_CONGESTION",
            "delay_hours": 36,
        },
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    disruption_id = res.json()["disruption_id"]
    alert_id = res.json()["alert_id"]
    assert alert_id, "disruption must raise an alert"

    # --- 2. alert appears in list with exposure ---
    res = await client.get("/api/alerts", headers=headers)
    assert res.status_code == 200
    alert_row = next(a for a in res.json()["alerts"] if a["id"] == alert_id)
    assert alert_row["financial_exposure"] > 0

    # --- 3. alert detail carries the breach payload ---
    res = await client.get(f"/api/alerts/{alert_id}", headers=headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["disruption"]["id"] == disruption_id
    assert detail["disruption"]["description"]

    # --- 4. acknowledge as operator ---
    op_headers = auth_headers_factory(seed_operator_user)
    res = await client.patch(
        f"/api/alerts/{alert_id}/acknowledge", json={"user_id": seed_operator_user.id}, headers=op_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == AlertStatus.ACKNOWLEDGED

    # --- 5. exactly 3 scored options, corridor option present ---
    res = await client.get(f"/api/alerts/{alert_id}/options", headers=headers)
    assert res.status_code == 200
    options = res.json()["options"]
    assert len(options) == 3
    keys = {o["option_key"] for o in options}
    assert "ACCEPT_DELAY" in keys
    assert "VIA_PIRAEUS" in keys
    assert "MODAL_SHIFT_AIR" in keys
    assert sum(1 for o in options if o["recommended"]) == 1

    # --- 6. approve the corridor reroute → legs rewritten at v2 ---
    res = await client.post(
        f"/api/alerts/{alert_id}/approve",
        json={"option_key": "VIA_PIRAEUS"},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    decision_id = res.json()["decision_id"]
    assert res.json()["action"] == "REROUTE"

    # old PLANNED leg replaced; new leg at route_version 2, chained to Rotterdam
    # Query via a brand-new session: db_session's identity map/transaction
    # snapshot predates the route's commit, and this assertion must prove what
    # is durably in the DB, not what this test's session remembers.
    reader_factory = create_session_factory(test_engine)
    async with reader_factory() as reader:
        legs = list(
            (
                await reader.execute(
                    select(Leg).where(Leg.shipment_id == shipment.id)
                )
            )
            .scalars()
            .all()
        )
    v2 = [l for l in legs if l.route_version == 2 and str(l.status) == "PLANNED"]
    assert len(v2) >= 1
    assert v2[-1].destination_id == rotterdam.id
    assert any(str(l.status) == "REPLACED" for l in legs)

    # --- 7. decision surfaces in the admin paper trail ---
    res = await client.get("/api/decisions", headers=headers)
    assert res.status_code == 200
    decision_row = next(d for d in res.json()["decisions"] if d["id"] == decision_id)
    assert decision_row["route_version_before"] == 1
    assert decision_row["route_version_after"] == 2
    assert decision_row["provenance"] == "DERIVED"

    # --- 8.5 copilot can explain what just happened (plain-language trace) ---
    res = await client.post(
        "/api/copilot/ask",
        json={"question": "Why was this shipment rerouted?", "shipment_id": shipment.id},
        headers=headers,
    )
    assert res.status_code in (200, 201), res.text
    copilot_body = res.json()
    assert copilot_body["provenance"], "copilot response must carry provenance"
    assert copilot_body["answer"], "copilot must return a non-empty answer"
    assert copilot_body["source"] in ("rules", "llm", "rules_fallback")

    # --- 8. alert resolves; duplicate approve → 409 ---
    res = await client.post(
        f"/api/alerts/{alert_id}/approve",
        json={"option_key": "ACCEPT_DELAY"},
        headers=headers,
    )
    assert res.status_code == 409

    # --- 9. immutable audit trail records the approval ---
    audits = list(
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "approve_reroute")
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].entity_id == decision_id

    # --- 10. analytics scorecard reflects the decision window ---
    res = await client.get("/api/analytics/summary", headers=headers)
    assert res.status_code == 200
    assert res.json()["total_shipments"] >= 1
