"""AI copilot endpoint (Definitive Plan — Phase 9).

POST /copilot/ask — natural-language answers about a shipment; LLM errors
degrade to rules (never a 500).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select
from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.enums import ShipmentStatus
from nexafreight.exceptions import ResourceNotFoundError
from nexafreight.models import Shipment, User
from nexafreight.schemas.ops import CopilotAskRequest, CopilotAskResponse
from nexafreight.services.copilot import answer_shipment_question

router = APIRouter()


import time
from collections import defaultdict
from nexafreight.exceptions import RateLimitExceededError

_COPILOT_REQUEST_TIMESTAMPS: dict[str, list[float]] = defaultdict(list)
COPILOT_WINDOW_SECONDS = 60
COPILOT_MAX_REQUESTS_PER_WINDOW = 10


def check_copilot_rate_limit(user_id: str) -> None:
    now = time.time()
    cutoff = now - COPILOT_WINDOW_SECONDS
    timestamps = [t for t in _COPILOT_REQUEST_TIMESTAMPS[user_id] if t > cutoff]
    if len(timestamps) >= COPILOT_MAX_REQUESTS_PER_WINDOW:
        retry_after = max(1, int(timestamps[0] + COPILOT_WINDOW_SECONDS - now))
        raise RateLimitExceededError(
            message=f"Copilot rate limit exceeded. Maximum {COPILOT_MAX_REQUESTS_PER_WINDOW} requests per minute.",
            retry_after=retry_after,
        )
    timestamps.append(now)
    _COPILOT_REQUEST_TIMESTAMPS[user_id] = timestamps


def reset_copilot_rate_limits() -> None:
    _COPILOT_REQUEST_TIMESTAMPS.clear()


@router.post("/ask", response_model=CopilotAskResponse)
async def ask(

    body: CopilotAskRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> CopilotAskResponse:
    """Ask the copilot a question about a shipment or active network state."""
    check_copilot_rate_limit(str(current_user.id))
    shipment: Shipment | None = None
    if body.shipment_id and body.shipment_id.strip():
        shipment = await session.get(Shipment, body.shipment_id.strip())

    # Fallback: if shipment_id is absent, mock/placeholder, or not found, resolve to
    # the most relevant active delayed or in-transit shipment in the live database.
    if shipment is None:
        stmt = (
            select(Shipment)
            .where(
                (Shipment.status == ShipmentStatus.DELAYED)
                | (Shipment.status == "DELAYED")
                | (Shipment.status == ShipmentStatus.IN_TRANSIT)
                | (Shipment.status == "IN_TRANSIT")
            )
            .order_by(Shipment.updated_at.desc())
            .limit(1)
        )
        shipment = (await session.execute(stmt)).scalars().first()

    if shipment is None:
        stmt_any = select(Shipment).limit(1)
        shipment = (await session.execute(stmt_any)).scalars().first()

    if shipment is None:
        raise ResourceNotFoundError("Shipment", body.shipment_id or "fleet")

    result = await answer_shipment_question(
        session,
        shipment=shipment,
        question=body.question,
        user=current_user,
    )
    return CopilotAskResponse(
        answer=result["answer"],
        source=result["source"],
        provenance=result["provenance"],
    )
