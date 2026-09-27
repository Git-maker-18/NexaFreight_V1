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
    # Road routing — speeds recalibrated to observed Indian values
    # (E7: was 1.4-1.8x hot; DPIIT-NCAER/Livemint govt study: 47-48 km/h
    # expressway, 37-38 km/h all-art/city. Regulatory_Tax_Reference.md SS8.)
    "road.speed.default": 42.0,
    "road.speed.expressway": 48.0,
    "road.speed.national_highway": 42.0,
    "road.speed.state_highway": 38.0,
    "road.circuity.default": 1.35,
    "road.circuity.expressway": 1.15,
    "road.circuity.national_highway": 1.20,
    "road.circuity.state_highway": 1.38,
    "road.halt_allowance_h_per_4_5h": 0.75,  # driver rest allowance per 4.5h driving (India MTWA 8h/day regime — NOT an EU 561/2006 analog; earlier doc mislabel corrected)
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
    # Disruptions — congestion tiers (Sim C / Sim C-validated: warn 1.5,
    # critical 2.5 = today's index vs 90-day baseline average)
    "disruption.congestion.ratio_warn": 1.5,
    "disruption.congestion.ratio_critical": 2.5,
    # E18 last-resort fallbacks: these mirror the inline shadow defaults the
    # planner (and demo-world builder) used to carry at their call sites --
    # registered here so the single source of truth holds. They fire ONLY
    # when parameter_empirical has no row for the key (fresh/test DBs);
    # real values come from the seeded parameter rows.
    "sea.feeder.speed_kn": 50.0,
    "sea.panamax.speed_kn": 50.0,
    "rail.dfc.speed_kmh": 50.0,
    "rail.conventional.speed_kmh": 50.0,
    "road.speed_kmh": 50.0,
    "sea.cost_usd_per_nm": 0.065,
    "rail.cost_usd_per_km": 0.065,
    "air.cost_usd_per_km": 0.065,
    "road.cost_usd_per_km": 0.065,
    "co2.sea_g_per_tonne_km": 62.0,
    "co2.rail_g_per_tonne_km": 62.0,
    "co2.air_g_per_tonne_km": 62.0,
    "co2.road_g_per_tonne_km": 62.0,
    "co2.road_g_with_toll": 62.0,
    "disruption.congestion.ratio_p90": 2.5,  # legacy alias of ratio_critical
    "disruption.delay.vessel_h": 24.0,
    "disruption.delay.weather_h": 48.0,
    "disruption.delay.default_h": 24.0,
    # Mode speeds and circuities
    "mode.speed.sea": 41.0,
    "mode.speed.air": 860.0,
    "mode.speed.road": 42.0,  # E7 recalibration (see road.speed.* above)
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
    # SLA penalty — LD (liquidated damages) norms: 0.5% per WEEK of delay,
    # WEEKLY rounding, capped at 10% of order value (Regulatory doc SS8).
    # Replaces the old 5%/day constant, which overstated LD norms ~7x and
    # biased every reroute decision toward REROUTE. Documented behavioral flip.
    "sla.penalty_pct_per_week": 0.5,
    "sla.penalty_cap_pct": 10.0,
    # Demurrage (E4 unification: ONE free-days source for reroute scoring AND
    # analytics exposure; India band ₹3–8k/box/day → see Regulatory doc §2)
    "demurrage.free_days": 4.0,
    "demurrage.rate_inr_per_box_day": 5500.0,  # JNPT band mid (INDUSTRY band Rs3-8k)
    "demurrage.reefer_inr_per_box_day": 11000.0,
    # Analytics active world (E3: exclude historical/parcel-era shipments)
    "analytics.exclude_provenances": "HISTORICAL",
    # Cargo insurance (INDUSTRY: ocean 0.3%, air 0.75%, road/rail 0.5% of
    # insured value; insured value = cargo value x 110% CIF-style uplift)
    "insurance.pct_of_value.sea": 0.003,
    "insurance.pct_of_value.air": 0.0075,
    "insurance.pct_of_value.road": 0.005,
    "insurance.pct_of_value.rail": 0.005,
    "insurance.insured_value_uplift": 1.10,
    # FX and carbon (MARKET as-of 2026-09; REGULATORY CBAM transitory price)
    "fx.usd_inr": 95.8,
    "carbon.price_usd_per_kg": 0.08,
    # Time-World (task 6): disabled by default = world time == real time.
    # 20_build_demo_world.py sets anchor/boot/warp when it seeds the world.
    "time_world.enabled": "false",
    "time_world.anchor_iso": "",
    "time_world.boot_real_iso": "",
    "time_world.warp": 1.0,
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


def get_bool(key: str, default: bool = False, *, with_provenance: bool = False) -> bool | tuple[bool, str]:
    """Boolean parameter getter.

    Accepts true/false in any case plus 1/0; unknown strings fail closed
    (False) with the raw value preserved in the provenance tuple.
    """
    raw = get_str(key, None, with_provenance=with_provenance)  # type: ignore[arg-type]
    if with_provenance:
        value, source = raw  # type: ignore[misc]
    else:
        value, source = raw, "DEFAULT"  # type: ignore[unreachable]
    low = (value or "").strip().lower()
    result = low in ("true", "1", "yes", "on") if low else bool(default)
    return (result, source) if with_provenance else result
