"""Frankfurter USD->INR reference rate into parameter_empirical."""
from __future__ import annotations

from datetime import UTC, datetime, time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.jobs.http import get_json
from nexafreight.models.parameter import ParameterEmpirical

_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR"
_KEY = "fx.usd_inr"
_SOURCE = "Frankfurter (ECB reference rates)"
_METHOD = "nightly job: USD->INR reference rate, unit INR per 1 USD"

async def run_fx(session: AsyncSession) -> str:
    """Fetch the latest USD->INR rate and upsert it. Returns a summary."""
    payload = await get_json(_URL)
    rate = float(payload["rates"]["INR"])
    rate_date = payload["date"]  # e.g. "2026-09-26"
    
    as_of = datetime.combine(
        datetime.fromisoformat(rate_date).date(), time.min, tzinfo=UTC
    )

    row = await session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == _KEY))
    existing = row.scalar_one_or_none()

    if existing is None:
        session.add(ParameterEmpirical(
            key=_KEY, value=f"{rate:.4f}", unit="INR per USD",
            source=_SOURCE, as_of=as_of,
            derivation_method=_METHOD, sample_count=1,
        ))
    else:
        existing.value = f"{rate:.4f}"
        existing.as_of = as_of
        existing.source = _SOURCE
        existing.sample_count = (existing.sample_count or 0) + 1

    await session.commit()

    # remove legacy dotted key written by nightly runs before OPS-FIX-1; safe to delete once fx.usd_inr exists.
    legacy_row = await session.execute(select(ParameterEmpirical).where(ParameterEmpirical.key == "fx.usd.inr"))
    legacy_obj = legacy_row.scalar_one_or_none()
    if legacy_obj is not None:
        await session.delete(legacy_obj)
        await session.commit()

    return f"fx.usd_inr={rate:.4f} (as_of {rate_date})"
