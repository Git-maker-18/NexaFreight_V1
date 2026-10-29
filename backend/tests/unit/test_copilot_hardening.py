"""Unit tests for Copilot hardening (Items 9-13)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from nexafreight.api.routes.copilot import reset_copilot_rate_limits
from nexafreight.enums import ShipmentStatus
from nexafreight.models.user import User
from nexafreight.services.copilot import (
    _demurrage_answer,
    load_shipment_context,
    needs_llm,
)


@pytest.fixture(autouse=True)
def clean_copilot_limits():
    reset_copilot_rate_limits()
    yield
    reset_copilot_rate_limits()


def test_needs_llm_word_boundaries():
    """needs_llm requires word boundaries so substring words do not trigger LLM."""
    assert needs_llm("Why is this shipment delayed?") is True
    assert needs_llm("Can you explain the route change?") is True
    assert needs_llm("What is the recommendation?") is True

    # Substrings should NOT trigger needs_llm
    assert needs_llm("Wait awhile before checking") is False
    assert needs_llm("Riskless is not a word here") is False


@pytest.mark.asyncio
async def test_copilot_demurrage_respects_status(make_shipment):
    """Demurrage returns 0 for planned or cancelled shipments."""
    planned_shp = await make_shipment(status=ShipmentStatus.PLANNED)
    answer = _demurrage_answer(planned_shp)
    assert "no port demurrage has accrued" in answer

    cancelled_shp = await make_shipment(status=ShipmentStatus.CANCELLED)
    answer_cancel = _demurrage_answer(cancelled_shp)
    assert "no port demurrage has accrued" in answer_cancel


def test_copilot_est_co2_uses_stored_leg_co2():
    """est_co2_kg sums stored leg co2_kg directly."""
    from unittest.mock import MagicMock
    leg1 = MagicMock()
    leg1.sequence_number = 1
    leg1.co2_kg = 123.4
    leg1.transport_mode = "SEA"
    leg1.status = "COMPLETED"
    leg1.distance_km = 1000.0
    leg1.planned_arrival = None

    leg2 = MagicMock()
    leg2.sequence_number = 2
    leg2.co2_kg = 456.6
    leg2.transport_mode = "ROAD"
    leg2.status = "PLANNED"
    leg2.distance_km = 500.0
    leg2.planned_arrival = None

    shp = MagicMock()
    shp.id = "shp-co2-test"
    shp.status = ShipmentStatus.IN_TRANSIT
    shp.primary_transport_mode = "SEA"
    shp.origin = None
    shp.origin_id = "USNYC"
    shp.destination = None
    shp.destination_id = "NLRTM"
    shp.container_count = 5
    shp.planned_departure = None
    shp.orders = []
    shp.alerts = []
    shp.legs = [leg1, leg2]

    ctx = load_shipment_context(shp)
    assert ctx["est_co2_kg"] == 580.0


@pytest.mark.asyncio
async def test_copilot_nonexistent_shipment_returns_404(
    client: AsyncClient,
    seed_operator_user: User,
    auth_headers: dict[str, str],
):
    """Providing a non-existent shipment_id must return 404, never substitute silently."""
    resp = await client.post(
        "/api/copilot/ask",
        json={"shipment_id": "non-existent-uuid-999", "question": "Where is it?"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_copilot_network_question_returns_overview(
    client: AsyncClient,
    seed_operator_user: User,
    auth_headers: dict[str, str],
):
    """Network-level questions without shipment_id return network overview."""
    resp = await client.post(
        "/api/copilot/ask",
        json={"question": "What is the network status?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "Network Overview" in data["answer"]


@pytest.mark.asyncio
async def test_copilot_rate_limit_11th_call_returns_429(
    client: AsyncClient,
    seed_operator_user: User,
    auth_headers: dict[str, str],
):
    """11th copilot call within a minute must return HTTP 429."""
    for i in range(10):
        resp = await client.post(
            "/api/copilot/ask",
            json={"question": f"Status check {i}"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    # 11th call
    resp = await client.post(
        "/api/copilot/ask",
        json={"question": "Status check 11"},
        headers=auth_headers,
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_copilot_offline_advisory_state(
    client: AsyncClient,
    seed_operator_user: User,
    auth_headers: dict[str, str],
    make_shipment,
):
    """When LLM is unavailable and needs_llm is triggered, show AI advisory offline message."""
    shp = await make_shipment(status=ShipmentStatus.IN_TRANSIT)

    resp = await client.post(
        "/api/copilot/ask",
        json={"shipment_id": shp.id, "question": "Why is this delayed?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "[AI Advisory Offline]" in data["answer"]
    assert shp.id in data["answer"]
    assert data["source"] == "rules_fallback"
