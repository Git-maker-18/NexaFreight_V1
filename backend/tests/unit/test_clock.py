"""Tests for the Time-World clock (task 6).

The clock must be: disabled-by-default (world == real time), exact under
warp math, and fail-open when misconfigured — a broken clock never takes
the demo down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from nexafreight.core import params
from nexafreight.core.clock import (
    KEY_ANCHOR,
    KEY_BOOT,
    KEY_ENABLED,
    KEY_WARP,
    configure,
    world_now,
    world_offset,
)


def _patch_cache(**entries):
    """Patch the param cache with the given key -> (value, source) pairs."""
    cache = {k: params.ParamEntry(value=v, source="TEST", is_policy=False) for k, v in entries.items()}
    return patch.object(params, "_PARAM_CACHE", cache)


def test_disabled_world_returns_real_time() -> None:
    """Day-1 default: time_world.enabled=false -> world_now == real now."""
    now = datetime.now(UTC)
    result = world_now(real_now=now)
    assert result == now
    assert result.tzinfo == UTC


def test_warp_math_exact() -> None:
    """world_now = anchor + (real - boot) * warp, computed exactly."""
    anchor = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    boot = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    real = boot + timedelta(hours=2)  # two real hours elapsed

    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: anchor.isoformat(),
            KEY_BOOT: boot.isoformat(),
            KEY_WARP: 438.3,  # Simulation A's warp: 1 demo day ≈ 3.3 real minutes
        }
    ):
        result = world_now(real_now=real)

    expected = anchor + timedelta(hours=2 * 438.3)
    assert result == expected


def test_world_started_mid_stream() -> None:
    """Anchor != boot: world starts 'in progress' (e.g., 30 days into ops)."""
    anchor = datetime(2026, 9, 24, tzinfo=UTC)
    boot = datetime(2026, 8, 25, tzinfo=UTC)  # world anchored 30 days after boot
    real = boot + timedelta(minutes=10)

    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: anchor.isoformat(),
            KEY_BOOT: boot.isoformat(),
            KEY_WARP: 1.0,
        }
    ):
        result = world_now(real_now=real)
    # warp 1.0: world = anchor + (real - boot) = anchor + 10 minutes
    assert result == anchor + timedelta(minutes=10)


def test_fail_open_on_missing_anchor() -> None:
    """Enabled but anchor/boot blank -> real time + no crash (fail-open)."""
    real = datetime.now(UTC)
    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: "",
            KEY_BOOT: "",
            KEY_WARP: 10.0,
        }
    ):
        assert world_now(real_now=real) == real


def test_fail_open_on_garbage_anchor() -> None:
    real = datetime.now(UTC)
    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: "not-a-date",
            KEY_BOOT: "2026-08-25T00:00:00+00:00",
            KEY_WARP: 2.0,
        }
    ):
        assert world_now(real_now=real) == real


def test_fail_open_on_zero_warp() -> None:
    """warp <= 0 is nonsense (world runs backwards / frozen) -> fail open."""
    real = datetime.now(UTC)
    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: "2026-09-24T00:00:00+00:00",
            KEY_BOOT: "2026-08-25T00:00:00+00:00",
            KEY_WARP: 0.0,
        }
    ):
        assert world_now(real_now=real) == real


def test_naive_inputs_get_utc_attached() -> None:
    """Naive anchor/boot/real are treated as UTC (DB round-trip convention)."""
    anchor = datetime(2026, 9, 24, 9, 0)  # naive
    boot = datetime(2026, 9, 24, 9, 0)  # naive
    real = datetime(2026, 9, 24, 10, 0)  # naive, 1h later

    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: anchor.isoformat(),
            KEY_BOOT: boot.isoformat(),
            KEY_WARP: 3.0,
        }
    ):
        result = world_now(real_now=real)
    assert result.tzinfo == UTC
    assert result == datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_configure_pure_map() -> None:
    """configure() returns the persisted key/value map, tz-normalizing."""
    anchor = datetime(2026, 9, 24, 9, 0)  # naive
    cfg = configure(anchor, warp=2.5)
    assert cfg[KEY_ENABLED] == "true"
    assert cfg[KEY_WARP] == "2.5"
    assert cfg[KEY_ANCHOR] == "2026-09-24T09:00:00+00:00"
    assert cfg[KEY_ANCHOR].endswith("+00:00")
    assert KEY_BOOT in cfg


def test_world_offset_helper() -> None:
    """world_offset walks backwards from world_now (seeding convenience)."""
    anchor = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    boot = anchor
    real = boot

    with _patch_cache(
        **{
            KEY_ENABLED: "true",
            KEY_ANCHOR: anchor.isoformat(),
            KEY_BOOT: boot.isoformat(),
            KEY_WARP: 1.0,
        }
    ):
        back = world_offset(days_back=5, real_now=real)
    assert back == anchor - timedelta(days=5)
