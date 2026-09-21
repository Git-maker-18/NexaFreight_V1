"""Parameter loading and caching module.

Provides synchronously accessible, strongly-typed getters for empirical and policy parameters,
with provenance passthrough. The cache should be refreshed periodically or at startup via
`refresh_parameters`.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple, overload, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models.parameter import ParameterEmpirical, ParameterPolicy

logger = logging.getLogger(__name__)

class ParamEntry(NamedTuple):
    value: str
    source: str
    is_policy: bool

# In-memory cache of all parameters
_PARAM_CACHE: dict[str, ParamEntry] = {}


async def refresh_parameters(session: AsyncSession) -> None:
    """Reload all parameters from the database into the in-memory cache."""
    global _PARAM_CACHE
    new_cache: dict[str, ParamEntry] = {}

    # Load policies
    policies = (await session.execute(select(ParameterPolicy))).scalars().all()
    for p in policies:
        new_cache[p.key] = ParamEntry(value=p.value, source="POLICY", is_policy=True)

    # Load empiricals
    empiricals = (await session.execute(select(ParameterEmpirical))).scalars().all()
    for e in empiricals:
        new_cache[e.key] = ParamEntry(value=e.value, source=e.source, is_policy=False)

    _PARAM_CACHE = new_cache
    logger.info("Refreshed parameter cache: %d parameters loaded.", len(_PARAM_CACHE))


# Central registry of documented fallback values (derived from calibration table)
FALLBACK_DEFAULTS: dict[str, Any] = {
    # Road routing
    "road.speed.default": 55.0,
    "road.speed.expressway": 70.0,
    "road.speed.national_highway": 50.0,
    "road.speed.state_highway": 40.0,
    "road.circuity.default": 1.35,
    "road.circuity.expressway": 1.15,
    "road.circuity.national_highway": 1.20,
    "road.circuity.state_highway": 1.38,
    "road.halt_allowance_h_per_4_5h": 0.75,
    # Air routing
    "air.taxi_hours": 0.3,
    "air.climb_descent_hours": 0.4,
    "air.cruise_speed_kmh": 860.0,
    "air.handling_hours": 12.0,
    # Sea routing
    "sea.speed.feeder": 15.0,
    "sea.speed.panamax": 19.0,
    "sea.speed.neo_panamax": 21.0,
    "sea.speed.slow_steamed": 17.0,
    "sea.canal_adder.suez_h": 14.0,
    # Disruptions
    "disruption.congestion.ratio_p90": 2.5,
    "disruption.delay.vessel_h": 24.0,
    "disruption.delay.weather_h": 48.0,
    "disruption.delay.default_h": 24.0,
    # Mode speeds and circuities
    "mode.speed.sea": 41.0,
    "mode.speed.air": 860.0,
    "mode.speed.road": 55.0,
    "mode.speed.rail": 60.0,
    "mode.circuity.sea": 1.15,
    "mode.circuity.air": 1.05,
    "mode.circuity.road": 1.20,
    "mode.circuity.rail": 1.10,
    # Planner & dwell
    "planner.handling_hours": 24.0,
    "planner.drayage_speed_kmh": 35.0,
    "port.dwell.p50.default": 24.0,
    "port.dwell.p90_ext.default": 48.0,
    "port.dwell.p50.INJNP": 22.0,
    "port.dwell.p90_ext.INJNP": 44.0,
    "port.dwell.p50.INMUN": 18.0,
    "port.dwell.p90_ext.INMUN": 36.0,
    "port.dwell.p50.INMAA": 26.0,
    "port.dwell.p90_ext.INMAA": 52.0,
    "port.dwell.p50.INVTZ": 24.0,
    "port.dwell.p90_ext.INVTZ": 48.0,
    "port.dwell.p50.INCCU": 38.0,
    "port.dwell.p90_ext.INCCU": 76.0,
    "port.dwell.p50.INCOK": 20.0,
    "port.dwell.p90_ext.INCOK": 40.0,
    "port.dwell.p50.NLRTM": 16.0,
    "port.dwell.p90_ext.NLRTM": 32.0,
    "port.dwell.p50.GRPIR": 20.0,
    "port.dwell.p90_ext.GRPIR": 40.0,
    "port.dwell.p50.SGSIN": 12.0,
    "port.dwell.p90_ext.SGSIN": 24.0,
    # SLA
    "sla.cushion_buffer_hours": 24.0,
}


@overload
def get_float(key: str, default: float | None = ...) -> float: ...
@overload
def get_float(key: str, default: float | None = ..., *, with_provenance: Literal[True]) -> tuple[float, str]: ...
@overload
def get_float(key: str, default: float | None = ..., *, with_provenance: bool = False) -> float | tuple[float, str]: ...

def get_float(key: str, default: float | None = None, *, with_provenance: bool = False) -> float | tuple[float, str]:
    entry = _PARAM_CACHE.get(key)
    if entry is not None:
        try:
            val = float(entry.value)
            return (val, entry.source) if with_provenance else val
        except ValueError:
            logger.warning("Parameter %s='%s' cannot be parsed as float", key, entry.value)
    
    if key in FALLBACK_DEFAULTS:
        fallback = float(FALLBACK_DEFAULTS[key])
    elif default is not None:
        fallback = default
    else:
        fallback = 0.0
    return (fallback, "DEFAULT") if with_provenance else fallback


@overload
def get_int(key: str, default: int | None = ...) -> int: ...
@overload
def get_int(key: str, default: int | None = ..., *, with_provenance: Literal[True]) -> tuple[int, str]: ...
@overload
def get_int(key: str, default: int | None = ..., *, with_provenance: bool = False) -> int | tuple[int, str]: ...

def get_int(key: str, default: int | None = None, *, with_provenance: bool = False) -> int | tuple[int, str]:
    entry = _PARAM_CACHE.get(key)
    if entry is not None:
        try:
            val = int(float(entry.value))
            return (val, entry.source) if with_provenance else val
        except ValueError:
            logger.warning("Parameter %s='%s' cannot be parsed as int", key, entry.value)
    if key in FALLBACK_DEFAULTS:
        fallback = int(FALLBACK_DEFAULTS[key])
    elif default is not None:
        fallback = default
    else:
        fallback = 0
    return (fallback, "DEFAULT") if with_provenance else fallback


@overload
def get_str(key: str, default: str | None = ...) -> str: ...
@overload
def get_str(key: str, default: str | None = ..., *, with_provenance: Literal[True]) -> tuple[str, str]: ...
@overload
def get_str(key: str, default: str | None = ..., *, with_provenance: bool = False) -> str | tuple[str, str]: ...

def get_str(key: str, default: str | None = None, *, with_provenance: bool = False) -> str | tuple[str, str]:
    entry = _PARAM_CACHE.get(key)
    if entry is not None:
        return (entry.value, entry.source) if with_provenance else entry.value
    if key in FALLBACK_DEFAULTS:
        fallback = str(FALLBACK_DEFAULTS[key])
    elif default is not None:
        fallback = default
    else:
        fallback = ""
    return (fallback, "DEFAULT") if with_provenance else fallback
