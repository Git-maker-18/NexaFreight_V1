"""Health check endpoint for infrastructure monitoring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.database import get_db_session

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str
    database: str
    version: str
    ml_models_loaded: bool = False
    models: dict[str, bool] = Field(
        default_factory=lambda: {"delay": False, "eta": False, "demand": False}
    )


class ValidationCheck(BaseModel):
    """One row of the validation matrix."""

    name: str
    actual: float
    ref: float
    tol: float
    ok: bool
    one_sided: bool | None = None


class ValidationMatrixResponse(BaseModel):
    """Live reference-validation matrix (Task 17): feeds the /validation page."""

    generated_at: str
    all_ok: bool
    pass_count: int
    total_count: int
    static: list[ValidationCheck]
    artifact: list[ValidationCheck]
    skips: list[str]


@router.get("/validation", response_model=ValidationMatrixResponse, tags=["health"])
async def validation_matrix() -> ValidationMatrixResponse:
    """Live validation matrix: every on-screen number vs published references."""
    from nexafreight.services.validation_matrix import build_matrix

    return ValidationMatrixResponse(**build_matrix())


@router.get("/", response_model=HealthResponse, tags=["health"])
@router.get("", response_model=HealthResponse, tags=["health"], include_in_schema=False)
async def health_check(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HealthResponse:
    """Check application and database health.

    Returns 200 if app and database are healthy, 503 if database is unreachable.
    This endpoint requires no authentication and is safe to expose for monitoring.
    """
    # Check database connectivity
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        database_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "database": "unreachable", "error": str(e)},
        ) from e

    ml_loaded = False
    models_dict = {"delay": False, "eta": False, "demand": False}
    reg = getattr(request.app.state, "ml_registry", None)
    if reg is not None:
        models_dict = {
            "delay": getattr(reg, "delay_loaded", False),
            "eta": getattr(reg, "eta_loaded", False),
            "demand": getattr(reg, "demand_loaded", False),
        }
        ml_loaded = getattr(reg, "is_loaded", False)

    return HealthResponse(
        status="healthy",
        database=database_status,
        version="0.1.0",
        ml_models_loaded=ml_loaded,
        models=models_dict,
    )
