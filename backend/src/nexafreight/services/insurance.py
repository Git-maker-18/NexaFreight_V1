"""Cargo insurance premium calculations.

New money line (audit calibration batch, Regulatory_Tax_Reference.md §8):
reroute options previously compared freight/carbon/SLA/demurrage but ignored
insurance even though a modal shift changes the premium class (ocean 0.3% vs
air 0.75% of insured value).

Pure functions, no I/O — same conventions as financial_engine. Rates are
INDUSTRY anchors; params keys carry the same numbers for single-source
configuration (insurance.pct_of_value.{sea,air,road,rail} and
insurance.insured_value_uplift).
"""

from __future__ import annotations

from nexafreight.enums import TransportMode

#: Premium as a fraction of insured value, by transport mode.
#: INDUSTRY anchors: ocean 0.30%, air 0.75%, road 0.50%, rail 0.50%
#: (rail shares the road rate — no separate public anchor; documented).
INSURANCE_PCT_BY_MODE: dict[str, float] = {
    "SEA": 0.003,
    "AIR": 0.0075,
    "ROAD": 0.005,
    "RAIL": 0.005,
}

#: Insured value = cargo value × 110% (CIF-style uplift, industry norm).
INSURED_VALUE_UPLIFT: float = 1.10


def _mode_key(mode: str | TransportMode) -> str:
    key = str(getattr(mode, "value", mode)).upper()
    return key if key in INSURANCE_PCT_BY_MODE else "SEA"


def calculate_insurance_premium(
    cargo_value: float,
    mode: str | TransportMode,
    *,
    uplift: float = INSURED_VALUE_UPLIFT,
) -> float:
    """Insurance premium for one leg/option.

    Args:
        cargo_value: Commercial value of the cargo being moved (USD).
        mode: Transport mode for the premium class.
        uplift: Insured-value multiplier (default 110%, CIF convention).

    Returns:
        Premium in USD: cargo_value × uplift × pct_of_value[mode].
    """
    return cargo_value * uplift * INSURANCE_PCT_BY_MODE[_mode_key(mode)]


def calculate_insurance_delta(
    cargo_value: float,
    from_mode: str | TransportMode,
    to_mode: str | TransportMode,
    *,
    uplift: float = INSURED_VALUE_UPLIFT,
) -> float:
    """Premium DELTA between two modes — the decision-relevant quantity.

    Insurance is incurred on every route; only the difference between
    options belongs in a reroute cost comparison. Same mode → 0.0.
    """
    return calculate_insurance_premium(cargo_value, to_mode, uplift=uplift) - (
        calculate_insurance_premium(cargo_value, from_mode, uplift=uplift)
    )
