"""Guard: every calibrated money/speed parameter traces to a published anchor.

Task 5 (calibration batch) — Regulatory_Tax_Reference.md §8 is the single
source for these values. If this test fails, someone moved a number without
updating the regulatory reference (or vice versa). No uncalibrated number is
allowed on screen.
"""

from __future__ import annotations

from nexafreight.core.params import FALLBACK_DEFAULTS
from nexafreight.services.financial_engine import (
    DEMURRAGE_DAILY_RATE,
    FREIGHT_RATE_PER_T_KM,
    SLA_PENALTY_PCT_PER_WEEK,
)


def test_sla_ld_norms() -> None:
    """LD norms: 0.5%/week, cap 10% (Reg. doc §8, INDUSTRY)."""
    assert FALLBACK_DEFAULTS["sla.penalty_pct_per_week"] == 0.5
    assert FALLBACK_DEFAULTS["sla.penalty_cap_pct"] == 10.0
    assert SLA_PENALTY_PCT_PER_WEEK == 0.005


def test_demurrage_jnpt_band() -> None:
    """Free days 4, ₹5,500/box/day band-mid, reefer ₹11,000 (JNPT bands)."""
    assert FALLBACK_DEFAULTS["demurrage.free_days"] == 4.0
    assert FALLBACK_DEFAULTS["demurrage.rate_inr_per_box_day"] == 5500.0
    assert FALLBACK_DEFAULTS["demurrage.reefer_inr_per_box_day"] == 11000.0
    # engine constant = ₹5,500 / fx 95.8
    assert DEMURRAGE_DAILY_RATE == 5500.0 / 95.8


def test_freight_anchors() -> None:
    """Air closes E9: $0.9/tkm = NCAER ₹72/tkm ÷ fx 88 (was 1.8 = 2× anchor)."""
    assert FALLBACK_DEFAULTS["fx.usd_inr"] == 95.8
    assert FREIGHT_RATE_PER_T_KM["AIR"] == 0.9
    assert FREIGHT_RATE_PER_T_KM["SEA"] == 0.012
    assert FREIGHT_RATE_PER_T_KM["ROAD"] == 0.0334  # ₹3.2/tkm ÷ 95.8
    assert FREIGHT_RATE_PER_T_KM["RAIL"] == 0.0146  # ₹1.4/tkm ÷ 95.8


def test_road_speeds_observed_not_nominal() -> None:
    """E7: speeds match the govt study (47–48 expressway, 37–38 city/art)."""
    assert FALLBACK_DEFAULTS["road.speed.expressway"] == 48.0
    assert FALLBACK_DEFAULTS["road.speed.national_highway"] == 42.0
    assert FALLBACK_DEFAULTS["road.speed.state_highway"] == 38.0
    assert FALLBACK_DEFAULTS["road.speed.default"] == 42.0
    assert FALLBACK_DEFAULTS["mode.speed.road"] == 42.0


def test_fx_and_carbon() -> None:
    assert FALLBACK_DEFAULTS["fx.usd_inr"] == 95.8
    assert FALLBACK_DEFAULTS["carbon.price_usd_per_kg"] == 0.08


def test_halt_allowance_is_mtwa_not_eu() -> None:
    """Value unchanged (0.75h per 4.5h driving); the EU-561 mislabel is what
    was corrected — India governs via MTWA 8h/day. Key name retained for
    compatibility; the params.py comment carries the relabel."""
    assert FALLBACK_DEFAULTS["road.halt_allowance_h_per_4_5h"] == 0.75
