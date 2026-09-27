"""Task 9 finish (external-audit finding F4): the dwell numbers that drive
the on-screen delay estimate must be pinned and bounded.

- every live port has a p50 registry value matching the C8 benchmark table
- p90_ext = 2.0 x p50 (the documented uniform-tail simplification, row C9)
- container p50 values sit below India's all-vessel average turnaround
- references.yaml pins the same numbers (drift fails eval/validate.py)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from nexafreight.core.params import FALLBACK_DEFAULTS

# Benchmark row C8 (External_Benchmark_Validation.md): CPPI-labelled
# per-port p50 dwell hours, ordering Kolkata (riverine) highest and
# Mundra/Singapore lowest.
C8_P50_HOURS: dict[str, float] = {
    "INJNP": 22.0,  # JNPT (Navi Mumbai)
    "INMUN": 18.0,  # Mundra
    "INMAA": 26.0,  # Chennai
    "INVTZ": 24.0,  # Vizag
    "INCCU": 38.0,  # Kolkata
    "INCOK": 20.0,  # Cochin
    "NLRTM": 16.0,  # Rotterdam
    "GRPIR": 20.0,  # Piraeus
    "SGSIN": 12.0,  # Singapore
}

# India all-vessel average turnaround, FY26 (~96 h in 2014). Container
# calls must sit below the all-vessel average.
ALL_VESSEL_UPPER_H = 48.84

P90_TAIL_RATIO = 2.0  # documented simplification (C9), empirical per-port p90 lands in task 15


def test_p50_registry_matches_c8_benchmark() -> None:
    for locode, hours in C8_P50_HOURS.items():
        assert FALLBACK_DEFAULTS[f"port.dwell.p50.{locode}"] == hours


def test_p90_ext_is_the_documented_tail_ratio() -> None:
    for locode, hours in C8_P50_HOURS.items():
        assert FALLBACK_DEFAULTS[f"port.dwell.p90_ext.{locode}"] == P90_TAIL_RATIO * hours


def test_container_dwell_below_allvessel_average() -> None:
    assert max(C8_P50_HOURS.values()) <= ALL_VESSEL_UPPER_H
    assert FALLBACK_DEFAULTS["port.dwell.p50.default"] <= ALL_VESSEL_UPPER_H


def test_references_yaml_pins_the_same_numbers() -> None:
    refs_path = Path(__file__).resolve().parents[2] / "eval" / "references.yaml"
    refs = yaml.safe_load(refs_path.read_text(encoding="utf-8"))
    for locode, hours in C8_P50_HOURS.items():
        assert refs["port_dwell_p50_hours"][locode]["value"] == hours
    assert refs["port_dwell_p90_ratio"]["value"] == P90_TAIL_RATIO
    assert refs["port_dwell_allvessel_upper_h"]["value"] == ALL_VESSEL_UPPER_H


def test_congestion_tiers_match_sim_c_design() -> None:
    assert FALLBACK_DEFAULTS["disruption.congestion.ratio_warn"] == 1.5
    assert FALLBACK_DEFAULTS["disruption.congestion.ratio_critical"] == 2.5
    # legacy alias must never diverge from critical
    assert FALLBACK_DEFAULTS["disruption.congestion.ratio_p90"] == FALLBACK_DEFAULTS[
        "disruption.congestion.ratio_critical"
    ]
