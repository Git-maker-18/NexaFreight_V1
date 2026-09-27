"""Shared feature contract (Task 19 / audit E10) + congestion features
(Task 15) for the ML tier.

E10 contract: ONE encoding implementation used by BOTH the training path
(scripts/09 + scripts/11) and the serving path (EtaQuantileModel). Before
this module, train-side unseen categorical levels became NaN (pandas
Categorical with a fixed category list) while serve-side unseen levels
mapped to the MISSING sentinel — a real train/serve skew. The contract
maps unseen levels to the sentinel on both sides.

Task 15: congestion feature library. The reserved slot documented in
features.py ("origin_congestion / dest_congestion are constant 1.0") is now
a real, as-of-safe computation over PortDailyStat-style data:
  - index_asof(port, date) uses ONLY observations STRICTLY BEFORE the date
    (no same-day leakage, matching the detector's baseline convention);
  - ports with fewer than CONGESTION_MIN_BASELINE_DAYS observations in the
    window yield the DEFAULT_CONGESTION_INDEX of 1.0 (cold start);
  - build_climatology derives a month-of-year pattern table per port.
DataCo-era training rows have no (port, date) intersection with port stats,
so they keep the documented constant 1.0 — the feature is wired for the
next training generation (v2) without touching the v1 champion contract.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, timedelta

import pandas as pd

from nexafreight.ml.constants import MISSING_SENTINEL

# ---------------------------------------------------------------------------
# Congestion feature constants (v2 contract; v1 artifacts are untouched)
# ---------------------------------------------------------------------------
DEFAULT_CONGESTION_INDEX = 1.0
CONGESTION_BASELINE_DAYS = 90
CONGESTION_MIN_BASELINE_DAYS = 30
CONGESTION_FEATURES = ("origin_congestion_index", "dest_congestion_index")
CLIMATOLOGY_MIN_DAYS_PER_MONTH = 30


# ---------------------------------------------------------------------------
# E10: the one encoder (train and serve both call this)
# ---------------------------------------------------------------------------
def encode_categorical_column(
    series: pd.Series,
    levels: list[str] | None = None,
    *,
    missing_sentinel: str = MISSING_SENTINEL,
) -> pd.Series:
    """Encode one categorical column: fillna -> str -> unseen->sentinel.

    With ``levels`` (the learned/committed category list), values outside the
    list degrade to the sentinel and the result is a Categorical with exactly
    ``levels + [sentinel]``. Without levels, categories are the observed
    values (training-side level learning).
    """
    vals = series.fillna(missing_sentinel).astype(str)
    if levels:
        vals = vals.where(vals.isin(list(levels)), missing_sentinel)
        cats = pd.Categorical(vals, categories=list(levels) + [missing_sentinel])
    else:
        cats = pd.Categorical(vals)
    return pd.Series(cats, index=series.index)


def encode_frame(
    frame: pd.DataFrame,
    *,
    feature_columns: list[str],
    cat_cols: list[str],
    num_cols: list[str],
    cat_levels: dict[str, list[str]] | None = None,
    missing_sentinel: str = MISSING_SENTINEL,
) -> pd.DataFrame:
    """Encode a raw frame into model input space (the serve-path semantics).

    - selects ``feature_columns`` in order, synthesizing NaN for missing ones
    - categorical: fillna->str, unseen levels -> sentinel, fixed categories
    - numeric: pd.to_numeric(errors="coerce")
    """
    levels = cat_levels or {}
    present = [c for c in feature_columns if c in frame.columns]
    df = frame[present].copy()
    for col in feature_columns:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[feature_columns]

    for col in cat_cols:
        if col in df.columns:
            df[col] = encode_categorical_column(
                df[col], levels.get(col), missing_sentinel=missing_sentinel
            )
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


# ---------------------------------------------------------------------------
# Task 15: as-of congestion lookups (leakage-safe) + climatology
# ---------------------------------------------------------------------------
class CongestionLookup:
    """In-memory as-of lookup over one port's daily congestion observations.

    ``index_asof(port, on_date)`` averages observations in
    ``(on_date - baseline_days, on_date)`` — strictly before the date — and
    returns the default when fewer than ``min_days`` observations exist.
    """

    def __init__(
        self,
        stats_by_port: dict[str, list[tuple[date, float]]],
        *,
        baseline_days: int = CONGESTION_BASELINE_DAYS,
        min_days: int = CONGESTION_MIN_BASELINE_DAYS,
        default: float = DEFAULT_CONGESTION_INDEX,
    ) -> None:
        self._by_port: dict[str, tuple[list[date], list[float]]] = {}
        for port, pairs in (stats_by_port or {}).items():
            sorted_pairs = sorted((d, float(v)) for d, v in pairs if d is not None)
            self._by_port[port] = (
                [d for d, _ in sorted_pairs],
                [v for _, v in sorted_pairs],
            )
        self._baseline_days = baseline_days
        self._min_days = min_days
        self._default = default

    @classmethod
    def from_frame(cls, stats_df: pd.DataFrame, **kwargs) -> "CongestionLookup":
        """Build from a DataFrame with columns [port_locode, stat_date, congestion_index]."""
        by_port: dict[str, list[tuple[date, float]]] = {}
        for port, d, v in stats_df[
            ["port_locode", "stat_date", "congestion_index"]
        ].itertuples(index=False):
            by_port.setdefault(str(port), []).append((d, float(v)))
        return cls(by_port, **kwargs)

    def index_asof(self, port_locode: str, on_date: date) -> float:
        entry = self._by_port.get(str(port_locode))
        if not entry:
            return self._default
        dates, values = entry
        window_start = on_date - timedelta(days=self._baseline_days)
        lo = bisect_right(dates, window_start)  # first obs strictly after window start
        hi = bisect_left(dates, on_date)  # first obs on/after the date -> excluded
        window = values[lo:hi]
        if len(window) < self._min_days:
            return self._default
        return sum(window) / len(window)

    def attach(self, df: pd.DataFrame, *, origin_port_col: str, dest_port_col: str, date_col: str) -> pd.DataFrame:
        """Add origin/dest congestion index columns (as-of safe, default 1.0)."""
        out = df.copy()
        origins: list[float] = []
        dests: list[float] = []
        for _, row in out.iterrows():
            d = row[date_col]
            d = d.date() if hasattr(d, "date") and not isinstance(d, date) else d
            origins.append(self.index_asof(row[origin_port_col], d))
            dests.append(self.index_asof(row[dest_port_col], d))
        out["origin_congestion_index"] = origins
        out["dest_congestion_index"] = dests
        return out


def build_climatology(
    stats_df: pd.DataFrame,
    *,
    min_days_per_month: int = CLIMATOLOGY_MIN_DAYS_PER_MONTH,
) -> dict[str, dict[str, float]]:
    """Month-of-year mean congestion per port from a long stats DataFrame.

    Ports/months with fewer than ``min_days_per_month`` observations are
    omitted (sparse coverage must not look like a pattern). Returns
    {port_locode: {"2026-03": mean, ...}} keyed by "MM" month strings.
    """
    table: dict[str, dict[int, list[float]]] = {}
    for port, d, v in stats_df[["port_locode", "stat_date", "congestion_index"]].itertuples(
        index=False
    ):
        table.setdefault(str(port), {}).setdefault(d.month, []).append(float(v))
    out: dict[str, dict[str, float]] = {}
    for port, by_month in table.items():
        kept = {
            f"{month:02d}": round(sum(vals) / len(vals), 4)
            for month, vals in sorted(by_month.items())
            if len(vals) >= min_days_per_month
        }
        if kept:
            out[port] = kept
    return out
