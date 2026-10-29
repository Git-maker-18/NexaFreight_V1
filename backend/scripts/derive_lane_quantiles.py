#!/usr/bin/env python3
"""derive_lane_quantiles.py
===========================
Derives empirical lane & mode transit quantile residuals (P10, P50, P85)
directly from the historical DataCo training split.

Usage:
    python scripts/derive_lane_quantiles.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json
import numpy as np
import pandas as pd

from nexafreight.ml.constants import (
    ETA_ACTUAL_DAYS_COLUMN,
    ETA_SCHEDULED_DAYS_COLUMN,
    LABEL_COLUMN,
    SPLIT_DATES,
    TIME_AXIS_COLUMN,
)
from nexafreight.ml.data_source import load_raw


def derive_lane_quantiles(quantiles: list[float] | None = None) -> dict[str, dict[str, float]]:
    if quantiles is None:
        quantiles = [0.10, 0.50, 0.85]

    raw = load_raw()
    actual = pd.to_numeric(raw[ETA_ACTUAL_DAYS_COLUMN], errors="coerce")
    sched = pd.to_numeric(raw[ETA_SCHEDULED_DAYS_COLUMN], errors="coerce")
    valid = (
        actual.notna()
        & sched.notna()
        & (actual >= 0)
        & (sched > 0)
        & raw[LABEL_COLUMN].notna()
    )
    raw = raw[valid].copy().reset_index(drop=True)
    actual = actual[valid].reset_index(drop=True)
    sched = sched[valid].reset_index(drop=True)
    raw["residual"] = (actual - sched).astype(float)

    time_s = pd.to_datetime(raw[TIME_AXIS_COLUMN], errors="coerce", utc=True)
    train_end = pd.Timestamp(SPLIT_DATES["train_end"], tz="UTC")
    train_df = raw[time_s < train_end].reset_index(drop=True)

    derived: dict[str, dict[str, float]] = {}

    for mode in ["AIR", "RAIL", "SEA"]:
        sub_y = train_df[train_df["shipping_mode"] == mode]["residual"].values
        derived[mode] = {}
        for q in quantiles:
            tag = f"p{int(round(q * 100))}"
            derived[mode][tag] = float(np.percentile(sub_y, q * 100))

    return derived


derive_lane_quantiles_table = derive_lane_quantiles


derive_lane_quantiles_table = derive_lane_quantiles

if __name__ == "__main__":
    table = derive_lane_quantiles()
    print("Empirical quantiles directly derived from DataCo training split:")
    print(json.dumps(table, indent=2))
