"""Time-World clock (Task 6, audit program rebuild/p0-mvp).

The demo world needs a single definition of "now" so that the order drip,
the world builder, and (later) the telemetry poller all agree, even when a
time-warp accelerates the simulation. Production code keeps using real UTC
time; only demo-world *creation* code consumes world_now().

Semantics
---------
real now            : datetime.now(UTC) — unchanged across the app (39 sites).
world anchor        : the simulated "today" the world was built for (ISO).
world boot (real)   : the real UTC instant the world was started.
warp                : world seconds per real second (1.0 = honest real time).

    world_now = anchor + (real_now - boot_real) * warp

Fail-open policy: if time_world.enabled is true but the anchor/boot keys are
missing or unparseable, world_now() returns real time and logs a warning —
a broken clock must never take the demo down.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from nexafreight.core import params

logger = logging.getLogger(__name__)

#: Params keys (single source; FALLBACK_DEFAULTS carries the day-1 values).
KEY_ENABLED = "time_world.enabled"
KEY_ANCHOR = "time_world.anchor_iso"
KEY_BOOT = "time_world.boot_real_iso"
KEY_WARP = "time_world.warp"


def configure(anchor: datetime, warp: float = 1.0, boot_real: datetime | None = None) -> dict[str, str]:
    """Return the param key/value map that (re)anchors the world.

    Pure function — the caller (scripts/20_build_demo_world.py) decides how
    to persist the returned pairs (parameter_empirical table), keeping this
    module import-light and trivially testable.
    """
    boot = boot_real or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    if boot.tzinfo is None:
        boot = boot.replace(tzinfo=UTC)
    return {
        KEY_ENABLED: "true",
        KEY_ANCHOR: anchor.isoformat(),
        KEY_BOOT: boot.isoformat(),
        KEY_WARP: str(float(warp)),
    }


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return None


def world_now(real_now: datetime | None = None) -> datetime:
    """The demo world's "now".

    Returns real UTC time when the world is disabled or misconfigured
    (fail-open). Pure in every input that matters: both real_now and all
    state come from the params cache, so tests can pin everything.
    """
    real = real_now or datetime.now(UTC)
    if real.tzinfo is None:
        real = real.replace(tzinfo=UTC)

    if not params.get_bool("time_world.enabled", False):
        return real

    anchor = _parse_iso(str(params.get_str(KEY_ANCHOR, "")))
    boot = _parse_iso(str(params.get_str(KEY_BOOT, "")))
    warp = params.get_float(KEY_WARP, 1.0)

    if anchor is None or boot is None or warp <= 0:
        logger.warning(
            "time_world enabled but anchor/boot/warp invalid — falling back to real time"
        )
        return real

    return anchor + (real - boot) * warp


def world_offset(days_back: int = 0, hours: float = 0.0, real_now: datetime | None = None) -> datetime:
    """world_now shifted backwards — convenience for seeding history.

    Negative offsets land in the world's past (in-flight shipments, delivered
    orders); the drip script uses this to build a coherent 150-day runway
    (Simulation A: ~8 orders/day, weekday-weighted).
    """
    return world_now(real_now=real_now) - timedelta(days=days_back, hours=hours)
