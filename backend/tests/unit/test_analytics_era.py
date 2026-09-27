"""Regression test for audit finding E3 (Built_In_Errors_Audit.md).

analytics._build_aggregates used select(Shipment) with no era/world guard.
Because scorecard windows are cumulative ("deadline <= now+1d"), every
2015–2018 parcel-era shipment sat inside the 'day' window forever, mixing
eras, geographies, and currencies into "today's" financials.

The fix stamps the parcel world Provenance.HISTORICAL (04_consolidate) and
excludes it from all three analytics selects via _active_world_filter().
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from nexafreight.enums import Provenance, ShipmentStatus
from nexafreight.models import Shipment
from nexafreight.api.routes.analytics import _active_world_filter


@pytest.mark.asyncio
async def test_historical_shipments_excluded_from_active_world(db_session, make_shipment):
    """HISTORICAL provenance must be invisible to the active-world filter;
    every other provenance (demo world) stays visible."""
    active = await make_shipment()
    historical = await make_shipment()
    historical.provenance = Provenance.HISTORICAL
    db_session.add(historical)
    await db_session.commit()

    result = await db_session.execute(select(Shipment).where(_active_world_filter()))
    visible = {s.id for s in result.scalars().all()}

    assert active.id in visible
    assert historical.id not in visible, (
        "HISTORICAL shipment leaked into the active world — the E3 era-mixing "
        "regression is back."
    )


def test_filter_defaults_to_excluding_historical_only():
    """The exclusion list must default to HISTORICAL only — filtering more
    would silently hide live-world rows; filtering less resurrects E3."""
    from nexafreight.core import params

    default = str(params.get_str("analytics.exclude_provenances", "HISTORICAL"))
    excluded = {p.strip().upper() for p in default.split(",") if p.strip()}
    assert excluded == {"HISTORICAL"}
