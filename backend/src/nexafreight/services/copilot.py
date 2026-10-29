"""AI copilot & automation (Definitive Plan — Phase 7).

Answers operators' natural-language questions about a shipment:

  rule path  — ETA, SLA status, demurrage; computed locally, deterministic.
  llm path   — "why / recommend / should we / explain / compare / trade-off…"
               — full node-A/B context is injected into the prompt.
  fallback   — any Gemini error degrades gracefully to the rule answer with
               source="rules_fallback" (never a 500).

All LLM interactions are recorded in audit_logs (action="llm_query") with
SHA-256 input/output hashes — a tamper-evident paper trail.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import ShipmentStatus
from nexafreight.models import AuditLog, Shipment
from nexafreight.models.alert import Alert
from nexafreight.services.alert_engine import latest_planned_arrival
from nexafreight.services.financial_engine import (
    DEMURRAGE_DAILY_RATE,
    DEMURRAGE_FREE_DAYS,
    calculate_demurrage,
)

logger = logging.getLogger(__name__)

#: Word-boundary regex routing to LLM when the question asks for judgment/explanation (Item 9).
_LLM_PATTERN = re.compile(
    r"\b(why|recommend|should we|should i|explain|compare|trade.?off|pros and cons|"
    r"advantage|risk|suggestion|recommendation|tradeoff)\b",
    re.IGNORECASE,
)


def needs_llm(question: str) -> bool:
    """True when the question asks for judgment/explanation → LLM path."""
    return bool(_LLM_PATTERN.search(question or ""))


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def load_shipment_context(shipment: Shipment) -> dict:
    """Compact, JSON-safe context snapshot of a shipment for prompts/rules.

    Uses stored leg CO2 directly (item 12).
    """
    legs = sorted(shipment.legs, key=lambda l: l.sequence_number)
    orders = shipment.orders
    total_revenue = sum(o.revenue for o in orders)
    total_shipping = sum(o.shipping_cost for o in orders)
    eta = latest_planned_arrival(shipment)

    # Use stored leg CO2 if available, otherwise sum valid entries
    stored_co2 = [leg.co2_kg for leg in legs if leg.co2_kg is not None]
    co2_kg = sum(stored_co2) if stored_co2 else 0.0

    return {
        "shipment_id": shipment.id,
        "status": str(shipment.status),
        "mode": str(shipment.primary_transport_mode),
        "origin": getattr(shipment.origin, "name", None) or str(shipment.origin_id),
        "destination": getattr(shipment.destination, "name", None)
        or str(shipment.destination_id),
        "container_count": shipment.container_count,
        "total_revenue_usd": total_revenue,
        "total_shipping_cost_usd": total_shipping,
        "planned_departure": shipment.planned_departure.isoformat()
        if shipment.planned_departure
        else None,
        "latest_eta": eta.isoformat() if eta else None,
        "est_co2_kg": round(co2_kg, 1),
        "orders": [
            {
                "order_number": o.order_number,
                "revenue_usd": o.revenue,
                "shipping_cost_usd": o.shipping_cost,
                "sla_status": str(o.sla_status),
                "sla_deadline": o.sla_deadline.isoformat(),
            }
            for o in orders
        ],
        "legs": [
            {
                "sequence": leg.sequence_number,
                "mode": str(leg.transport_mode),
                "status": str(leg.status),
                "distance_km": leg.distance_km,
                "co2_kg": leg.co2_kg,
                "planned_arrival": leg.planned_arrival.isoformat()
                if leg.planned_arrival
                else None,
            }
            for leg in legs
        ],
        "open_alerts": [
            {"severity": str(a.severity), "exposure_usd": a.financial_exposure}
            for a in shipment.alerts
            if str(a.status) != "RESOLVED"
        ],
    }


# ---------------------------------------------------------------------------
# Rule answers
# ---------------------------------------------------------------------------


def _demurrage_answer(shipment: Shipment) -> str:
    """Rules: quote live demurrage paper trail for the shipment (item 10 & 12)."""
    status_str = str(shipment.status).upper()
    if status_str in ("PLANNED", "CANCELLED", "CREATED"):
        return f"Shipment {shipment.id} is {status_str}; no port demurrage has accrued."

    eta = latest_planned_arrival(shipment)
    dwell_days = 0
    if eta is not None:
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=UTC)
        dwell_days = max(0, (datetime.now(UTC) - eta).days)

    per_container = calculate_demurrage(
        extra_days=dwell_days,
        free_days=DEMURRAGE_FREE_DAYS,
        daily_rate=DEMURRAGE_DAILY_RATE,
    )
    total = per_container * max(1, shipment.container_count)
    return (
        f"Shipment {shipment.id} demurrage exposure: ~${total:,.0f} "
        f"({shipment.container_count} container(s) × "
        f"${DEMURRAGE_DAILY_RATE:,.0f}/day after {DEMURRAGE_FREE_DAYS} free days; "
        f"current dwell {dwell_days} day(s) past planned arrival)."
    )


def _rules_answer(shipment: Shipment) -> str:
    """Rules: ETA / SLA / demurrage from live data — deterministic (item 10)."""
    orders = shipment.orders
    eta = latest_planned_arrival(shipment)
    now = datetime.now(UTC)
    if eta is not None and eta.tzinfo is None:
        eta = eta.replace(tzinfo=UTC)

    if orders:
        order = min(orders, key=lambda o: o.sla_deadline)
        deadline = order.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if eta and eta > deadline:
            days = max(1, (eta - deadline).days)
            return (
                f"Shipment {shipment.id} SLA breach: order {order.order_number} misses its deadline "
                f"{deadline:%Y-%m-%d} by ~{days} day(s) "
                f"(latest planned arrival {eta:%Y-%m-%d})."
            )
        eta_text = f"{eta:%Y-%m-%d}" if eta else "unknown"
        return (
            f"Shipment {shipment.id} on track: order {order.order_number} due {deadline:%Y-%m-%d}; "
            f"current ETA {eta_text} ({str(order.sla_status).lower()})."
        )
    if eta is None:
        return f"Shipment {shipment.id}: no schedule data is available for this shipment yet."
    days_out = max(0, (eta - now).days)
    return (
        f"Shipment {shipment.id} is currently estimated to arrive {eta:%Y-%m-%d} "
        f"(~{days_out} day(s) out)."
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def answer_shipment_question(
    session: AsyncSession,
    *,
    shipment: Shipment,
    question: str,
    adapter=None,
    user=None,
) -> dict:
    """Answer an operator question for a specific shipment.

    Always calls needs_llm() first (item 9).
    State which shipment it refers to (item 10).
    Offline LLM returns advisory notice + deterministic facts (item 11).
    """
    await session.refresh(shipment, ["legs", "orders", "alerts", "origin", "destination"])
    context = load_shipment_context(shipment)

    base_eta_status = _rules_answer(shipment)
    base_demurrage = _demurrage_answer(shipment)

    # 1. Call needs_llm() first! If not judgment/explanation question, use deterministic rules
    q_lower = (question or "").lower()
    if not needs_llm(question):
        if "demurrage" in q_lower or "fee" in q_lower:
            return {"answer": base_demurrage, "source": "rules", "provenance": "DERIVED"}
        return {"answer": base_eta_status, "source": "rules", "provenance": "DERIVED"}

    # 2. Try LLM path
    source = "rules_fallback"

    if adapter is None:
        from nexafreight.adapters.llm.gemini import GeminiAdapter
        from nexafreight.adapters.llm.groq import GroqAdapter
        from nexafreight.adapters.llm.ollama import OllamaAdapter
        from nexafreight.config import get_settings

        _settings = get_settings()
        _groq_key = (
            _settings.groq_api_key.get_secret_value()
            if getattr(_settings, "groq_api_key", None)
            else None
        )
        groq = GroqAdapter(
            api_key=_groq_key,
            model=getattr(_settings, "groq_model", "llama-3.3-70b-versatile"),
        )
        _gemini_key = (
            _settings.gemini_api_key.get_secret_value()
            if _settings.gemini_api_key
            else None
        )
        gemini = GeminiAdapter(
            model_name=_settings.gemini_model,
            api_key=_gemini_key,
        )
        ollama = OllamaAdapter(
            base_url=_settings.ollama_base_url,
            model=_settings.ollama_model,
        )
        adapter = groq if groq.available else (gemini if gemini.available else ollama)

    # Format user question for model context
    user_question = question.strip()

    # Separate system and user messages; json.dumps the context (item 13)
    system_instruction = (
        "You are the NexaFreight AI Copilot. You provide professional, descriptive, "
        "and analytical answers to freight operator questions.\n\n"
        "STYLE DIRECTIVE:\n"
        "1. Never give one-word answers. Use structured Markdown paragraphs.\n"
        "2. When numbers appear, cite them from SYSTEM COMPUTED FACTS or SHIPMENT DATA verbatim - never invent figures.\n"
        f"3. State clearly in your response that this analysis applies to Shipment {shipment.id}."
    )

    user_message = (
        f"[SYSTEM COMPUTED FACTS]\n- Delivery Status: {base_eta_status}\n- Demurrage: {base_demurrage}\n[END FACTS]\n\n"
        f"[SHIPMENT DATA]\n{json.dumps(context, indent=2)}\n[END DATA]\n\n"
        f"[USER QUESTION]\n{user_question}\n[END QUESTION]"
    )

    full_prompt = f"[SYSTEM INSTRUCTION]\n{system_instruction}\n\n{user_message}"

    if getattr(adapter, "available", False):
        raw_answer = await adapter.complete(full_prompt)
        if raw_answer:
            answer = raw_answer.strip()
            source = "llm"
            _record_llm_audit(
                session,
                shipment=shipment,
                question=question,
                answer=answer,
                user=user,
            )
            await session.commit()
            return {"answer": answer, "source": source, "provenance": "DERIVED"}

    # 3. LLM unavailable — state offline and show deterministic facts (item 11)
    logger.warning("Copilot LLM unavailable; serving rules_fallback with offline advisory notice")
    fallback_fact = base_demurrage if ("demurrage" in q_lower or "fee" in q_lower) else base_eta_status
    answer = f"[AI Advisory Offline] Operating in deterministic fallback mode.\n\n{fallback_fact}"

    _record_llm_audit(
        session,
        shipment=shipment,
        question=question,
        answer=answer,
        user=user,
        note="all_llm_unavailable_fallback",
    )
    await session.commit()
    return {"answer": answer, "source": source, "provenance": "DERIVED"}


async def answer_network_question(
    session: AsyncSession,
    *,
    question: str,
    adapter=None,
    user=None,
) -> dict:
    """Answer fleet/network-level questions without returning one shipment's answer (item 9)."""
    total_shipments = (await session.execute(select(func.count(Shipment.id)))).scalar() or 0
    delayed_stmt = select(func.count(Shipment.id)).where(
        (Shipment.status == ShipmentStatus.DELAYED) | (Shipment.status == "DELAYED")
    )
    delayed_shipments = (await session.execute(delayed_stmt)).scalar() or 0
    in_transit_stmt = select(func.count(Shipment.id)).where(
        (Shipment.status == ShipmentStatus.IN_TRANSIT) | (Shipment.status == "IN_TRANSIT")
    )
    in_transit_shipments = (await session.execute(in_transit_stmt)).scalar() or 0
    open_alerts = (
        await session.execute(select(func.count(Alert.id)).where(Alert.status != "RESOLVED"))
    ).scalar() or 0

    network_summary = (
        f"Network Overview: {total_shipments} total shipments "
        f"({in_transit_shipments} in-transit, {delayed_shipments} delayed). "
        f"{open_alerts} active open alert(s) across global corridors."
    )

    if not needs_llm(question):
        return {"answer": network_summary, "source": "rules", "provenance": "DERIVED"}

    # LLM path for network questions
    if adapter is None:
        from nexafreight.adapters.llm.gemini import GeminiAdapter
        from nexafreight.adapters.llm.groq import GroqAdapter
        from nexafreight.adapters.llm.ollama import OllamaAdapter
        from nexafreight.config import get_settings

        _settings = get_settings()
        _groq_key = (
            _settings.groq_api_key.get_secret_value()
            if getattr(_settings, "groq_api_key", None)
            else None
        )
        groq = GroqAdapter(
            api_key=_groq_key,
            model=getattr(_settings, "groq_model", "llama-3.3-70b-versatile"),
        )
        _gemini_key = (
            _settings.gemini_api_key.get_secret_value()
            if _settings.gemini_api_key
            else None
        )
        gemini = GeminiAdapter(
            model_name=_settings.gemini_model,
            api_key=_gemini_key,
        )
        ollama = OllamaAdapter(
            base_url=_settings.ollama_base_url,
            model=_settings.ollama_model,
        )
        adapter = groq if groq.available else (gemini if gemini.available else ollama)

    if getattr(adapter, "available", False):
        prompt = (
            f"[SYSTEM INSTRUCTION]\nYou are NexaFreight AI Copilot answering a network-level inquiry.\n"
            f"[NETWORK DATA]\n{network_summary}\n"
            f"[USER QUESTION]\n{question}\n"
        )
        raw_answer = await adapter.complete(prompt)
        if raw_answer:
            return {"answer": raw_answer.strip(), "source": "llm", "provenance": "DERIVED"}

    return {
        "answer": f"[AI Advisory Offline] Operating in deterministic fallback mode.\n\n{network_summary}",
        "source": "rules_fallback",
        "provenance": "DERIVED",
    }


def _record_llm_audit(
    session: AsyncSession,
    *,
    shipment: Shipment,
    question: str,
    answer: str,
    user=None,
    note: str | None = None,
) -> None:
    """Paper trail: every LLM interaction gets SHA-256 input/output hashes."""
    session.add(
        AuditLog(
            actor_type="user" if user is not None else "system",
            actor_id=getattr(user, "id", None),
            actor_name=getattr(user, "full_name", None) or "copilot",
            action="llm_query",
            entity_type="shipment",
            entity_id=shipment.id,
            input_hash=hashlib.sha256(question.encode()).hexdigest(),
            output_hash=hashlib.sha256(answer.encode()).hexdigest(),
            details_json=f'{{"note": "{note or "ok"}"}}',
        )
    )
