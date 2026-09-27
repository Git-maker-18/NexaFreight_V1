"""Unit tests for the AI copilot (Definitive Plan — Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models import AuditLog
from nexafreight.services.copilot import (
    answer_shipment_question,
    needs_llm,
)


NOW = datetime.now(UTC)


class _FakeAdapter:
    def __init__(self, answer: str | None = "Because the corridor is cheaper…"):
        self._answer = answer

    @property
    def available(self) -> bool:
        return self._answer is not None

    async def complete(self, prompt: str) -> str | None:
        if self._answer is None:
            return None
        assert "shipment" in prompt.lower()  # context got injected
        return self._answer


def test_needs_llm_routing() -> None:
    """Judgment questions → LLM; status questions → rules."""
    assert needs_llm("Why is this shipment delayed?")
    assert needs_llm("Should we re-route this shipment?")
    assert needs_llm("What do you recommend for this trade-off?")
    assert needs_llm("Explain the risk of the current plan")
    assert not needs_llm("When will this shipment arrive?")
    assert not needs_llm("What is the demurrage on this shipment?")


async def test_rules_path_eta_and_sla(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """No LLM requested for status questions — rules handle ETA/SLA."""
    shipment = await make_shipment(status="IN_TRANSIT")
    await make_leg(
        shipment_id=shipment.id,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=3),
    )
    await make_order(
        order_number="ORD-CP-1",
        shipment=shipment,
        sla_deadline=NOW + timedelta(days=5),
    )
    result = await answer_shipment_question(
        db_session, shipment=shipment, question="When will this shipment arrive?"
    )
    assert result["source"] == "rules"
    assert "due" in result["answer"].lower() or "eta" in result["answer"].lower()
    assert result["provenance"] == "DERIVED"

    # SLA breach phrased as such when late
    await make_order(
        order_number="ORD-CP-2",
        shipment=shipment,
        sla_deadline=NOW + timedelta(days=1),
    )
    result = await answer_shipment_question(
        db_session, shipment=shipment, question="Are we on time for SLA?"
    )
    assert "breach" in result["answer"].lower()


async def test_demurrage_payload_rule(
    db_session: AsyncSession, make_shipment, make_leg
) -> None:
    """Demurrage questions quote containers × $150/day after 4 free days."""
    shipment = await make_shipment(status="IN_TRANSIT", container_count=2)
    # arrived 6 days ago per plan but not delivered → dwell 6 days
    await make_leg(
        shipment_id=shipment.id,
        planned_departure=NOW - timedelta(days=10),
        planned_arrival=NOW - timedelta(days=6),
    )
    result = await answer_shipment_question(
        db_session, shipment=shipment, question="What is the demurrage on this shipment?"
    )
    assert result["source"] == "rules"
    # 6 days dwell → 2 billable days × $57.4 (Rs5,500 / fx 95.8) × 2 boxes = $230
    assert "$230" in result["answer"]


async def test_llm_path_calls_adapter_and_audits(
    db_session: AsyncSession, make_shipment, make_order, make_leg, seed_operator_user
) -> None:
    shipment = await make_shipment(status="IN_TRANSIT")
    await make_leg(shipment_id=shipment.id)
    await make_order(order_number="ORD-CP-3", shipment=shipment)

    adapter = _FakeAdapter(answer="The corridor via Piraeus is $560 cheaper than accepting the SLA penalty.")
    result = await answer_shipment_question(
        db_session,
        shipment=shipment,
        question="Why should we divert?",
        adapter=adapter,
        user=seed_operator_user,
    )
    assert result["source"] == "llm"
    assert "Piraeus" in result["answer"]

    # Audit entry holds SHA-256 input/output hashes
    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "llm_query")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].input_hash and len(rows[0].input_hash) == 64
    assert rows[0].output_hash and len(rows[0].output_hash) == 64
    assert rows[0].entity_id == shipment.id


async def test_llm_failure_falls_back_to_rules(
    db_session: AsyncSession, make_shipment, make_order, make_leg
) -> None:
    """Adapter unavailable → rules_fallback, never raises."""
    shipment = await make_shipment(status="IN_TRANSIT")
    await make_leg(shipment_id=shipment.id)
    await make_order(order_number="ORD-CP-4", shipment=shipment)

    result = await answer_shipment_question(
        db_session,
        shipment=shipment,
        question="Why should we re-route?",
        adapter=_FakeAdapter(answer=None),
    )
    assert result["source"] == "rules_fallback"
    assert result["answer"]
    assert result["provenance"] == "DERIVED"
