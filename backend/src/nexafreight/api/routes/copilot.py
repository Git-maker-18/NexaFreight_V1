"""Copilot natural-language endpoints (Definitive Plan — Phase 7)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.database import get_db_session
from nexafreight.dependencies import get_current_user
from nexafreight.exceptions import (
    RateLimitExceededError,
    ResourceNotFoundError,
    ValidationError,
)
from nexafreight.models import Shipment, User
from nexafreight.schemas.ops import CopilotAskRequest, CopilotAskResponse
from nexafreight.services.copilot import (
    answer_network_question,
    answer_shipment_question,
)

router = APIRouter()
logger = logging.getLogger(__name__)

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
    if len(body.question) > 500:
        raise ValidationError("Question exceeds maximum allowed length of 500 characters")
    check_copilot_rate_limit(str(current_user.id))

    # If shipment_id is provided, look it up strictly; if not found, 404 (item 10)
    if body.shipment_id and body.shipment_id.strip():
        target_id = body.shipment_id.strip()
        shipment = await session.get(Shipment, target_id)
        if shipment is None:
            raise ResourceNotFoundError("Shipment", target_id)

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

    # If no shipment_id is given, answer as a network-level question (item 9)
    result = await answer_network_question(
        session,
        question=body.question,
        user=current_user,
    )
    return CopilotAskResponse(
        answer=result["answer"],
        source=result["source"],
        provenance=result["provenance"],
    )
