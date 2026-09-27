"""Tasks 19 + 15: the shared feature contract and congestion features.

The skew tests are the E10 guarantee: the train-side encoder
(scripts/11 via the contract) and the serve-side encoder
(EtaQuantileModel._encode_frame) are the SAME implementation, and produce
identical frames and identical booster predictions on identical inputs.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from nexafreight.ml.feature_contract import (
    DEFAULT_CONGESTION_INDEX,
    CongestionLookup,
    build_climatology,
    encode_categorical_column,
    encode_frame,
)

# ---------------------------------------------------------------------------
# E10: encoder contract
# ---------------------------------------------------------------------------


def test_encode_categorical_unseen_maps_to_sentinel_not_nan() -> None:
    s = pd.Series(["SEA", "AIR", "MOON", None])
    out = encode_categorical_column(s, ["AIR", "SEA"])
    vals = list(out.astype(str))
    assert vals == ["SEA", "AIR", "__MISSING__", "__MISSING__"]
    assert list(out.cat.categories) == ["AIR", "SEA", "__MISSING__"]


def test_encode_frame_orders_and_coerces() -> None:
    frame = pd.DataFrame(
        {
            "b_num": ["3.5", "oops"],
            "a_cat": ["x", "zzz"],
            "extra_ignored": [1, 2],
        }
    )
    out = encode_frame(
        frame,
        feature_columns=["a_cat", "b_num", "ghost"],
        cat_cols=["a_cat"],
        num_cols=["b_num"],
        cat_levels={"a_cat": ["x", "y"]},
    )
    assert list(out.columns) == ["a_cat", "b_num", "ghost"]
    assert out["a_cat"].astype(str).tolist() == ["x", "__MISSING__"]
    assert pd.isna(out["b_num"].iloc[1]) and out["b_num"].iloc[0] == 3.5
    assert out["ghost"].isna().all()


def test_skew_train_and_serve_encoders_agree() -> None:
    """E10 guarantee on the committed champion: contract == serve encoder."""
    backend = Path(__file__).resolve().parents[2]
    model_dir = backend / "models" / "eta_quantile"
    parquet = backend / "data" / "processed" / "test.parquet"
    if not (model_dir / "model.joblib").exists() or not parquet.exists():
        pytest.skip("champion artifact / parquets not in this checkout")

    import joblib

    from nexafreight.ml.eta_model import EtaQuantileModel

    bundle = joblib.load(model_dir / "model.joblib")
    frame = pd.read_parquet(parquet).head(200)

    contract_out = encode_frame(
        frame,
        feature_columns=list(bundle["feature_columns"]),
        cat_cols=list(bundle["categorical_columns"]),
        num_cols=list(bundle["numeric_columns"]),
        cat_levels=bundle.get("category_levels") or {},
    )
    model = EtaQuantileModel()
    model.load(model_dir)
    serve_out = model._encode_frame(frame)

    pd.testing.assert_frame_equal(contract_out, serve_out)

    for tag, booster in bundle["models"].items():
        a = booster.predict(contract_out)
        b = booster.predict(serve_out)
        assert (a == b).all(), f"booster {tag} diverged between train/serve encodings"


# ---------------------------------------------------------------------------
# Task 15: as-of congestion (leakage-safe) + climatology
# ---------------------------------------------------------------------------


def _lookup(min_days: int = 20) -> CongestionLookup:
    pairs = [(date(2026, 6, d), 1.0) for d in range(1, 28)]  # 27 calm days
    pairs.append((date(2026, 7, 1), 5.0))  # the spike day
    return CongestionLookup({"INJNP": pairs}, min_days=min_days)


def test_asof_excludes_the_day_itself_no_leakage() -> None:
    lk = _lookup()
    # Spike-day value (5.0 on Jul 1) must NOT be in Jul 1's own window.
    assert lk.index_asof("INJNP", date(2026, 7, 1)) == 1.0
    # From Jul 2 the spike is in the (strictly-past) window: (27*1 + 5)/28.
    assert lk.index_asof("INJNP", date(2026, 7, 2)) == pytest.approx((27 + 5.0) / 28)


def test_asof_cold_start_defaults() -> None:
    lk = _lookup(min_days=20)
    assert lk.index_asof("XXXXX", date(2026, 7, 2)) == DEFAULT_CONGESTION_INDEX
    # 3 observations < min_days -> default, never a thin-window mean
    sparse = CongestionLookup({"INMUN": [(date(2026, 7, 1), 9.0)] * 3}, min_days=20)
    assert sparse.index_asof("INMUN", date(2026, 7, 2)) == DEFAULT_CONGESTION_INDEX


def test_attach_adds_default_and_real_columns() -> None:
    lk = _lookup(min_days=20)
    df = pd.DataFrame(
        {
            "o_port": ["INJNP", "XXXXX"],
            "d_port": ["XXXXX", "INJNP"],
            "sched": [date(2026, 7, 1), date(2026, 7, 2)],
        }
    )
    out = lk.attach(df, origin_port_col="o_port", dest_port_col="d_port", date_col="sched")
    assert out["origin_congestion_index"].tolist()[0] == pytest.approx(1.0)
    assert out["dest_congestion_index"].tolist()[1] == pytest.approx((27 + 5.0) / 28)
    assert out["origin_congestion_index"].tolist()[1] == DEFAULT_CONGESTION_INDEX


def test_climatology_requires_minimum_coverage() -> None:
    rows = []
    for m in range(1, 13):  # 12 months x 28 days for INJNP
        for d in range(1, 29):
            rows.append(("INJNP", date(2026, m, d), 1.0 + (m % 3) * 0.1))
    for d in range(1, 6):  # 5 days only for INMUN -> below min
        rows.append(("INMUN", date(2026, 5, d), 3.0))
    table = build_climatology(
        pd.DataFrame(rows, columns=["port_locode", "stat_date", "congestion_index"]),
        min_days_per_month=28,
    )
    assert set(table) == {"INJNP"}
    assert len(table["INJNP"]) == 12
    assert table["INJNP"]["01"] == pytest.approx(1.1)
