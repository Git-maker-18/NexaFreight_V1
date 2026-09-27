import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from nexafreight.eval.delay_benchmark import (
    validate_features,
    group_split,
    calibration_table,
    leakage_verdict,
    build_frame,
    PRE_SHIPMENT_ALLOWLIST,
    LEAK_COLUMNS,
    GROUP_COLUMN
)

def test_validate_features_rejects_leak_column():
    with pytest.raises(ValueError, match="Leak column"):
        validate_features(["Type", "Late_delivery_risk"])

def test_validate_features_rejects_unknown_column():
    with pytest.raises(ValueError, match="Unknown column"):
        validate_features(["Type", "Customer City"])

def test_validate_features_accepts_allowlist():
    assert validate_features(PRE_SHIPMENT_ALLOWLIST) == sorted(PRE_SHIPMENT_ALLOWLIST)

def test_group_split_disjoint_orders():
    # 2000 rows, 300 orders
    orders = np.repeat(np.arange(300), 2000 // 300 + 1)[:2000]
    df = pd.DataFrame({GROUP_COLUMN: orders, "val": np.arange(2000)})
    train, val, test = group_split(df, seed=42)
    
    assert 1300 <= len(train) <= 1500
    assert 200 <= len(val) <= 400
    assert 200 <= len(test) <= 400
    
    t_ids = set(train[GROUP_COLUMN])
    v_ids = set(val[GROUP_COLUMN])
    te_ids = set(test[GROUP_COLUMN])
    
    assert t_ids.isdisjoint(v_ids)
    assert v_ids.isdisjoint(te_ids)
    assert t_ids.isdisjoint(te_ids)

def test_group_split_keeps_lines_together():
    orders = [100]*5 + [101]*5 + [102]*5
    df = pd.DataFrame({GROUP_COLUMN: orders, "val": np.arange(15)})
    train, val, test = group_split(df, seed=42)
    
    order_id = 100
    counts = [sum(frame[GROUP_COLUMN] == order_id) for frame in (train, val, test)]
    assert sorted(counts) == [0, 0, 5]

def test_calibration_table_shape_and_monotone_bins():
    y = np.array([0, 1, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.4, 0.8, 0.9])
    
    table = calibration_table(y, p, n_bins=10)
    assert len(table) == 10
    
    assert sum(b["count"] for b in table) == 5
    for b in table:
        assert 0.0 <= b["empirical_rate"] <= 1.0

def test_leakage_verdict_tripwire():
    assert leakage_verdict(0.969) == "OK"
    assert leakage_verdict(0.97) == "INFLATED_SUSPECTED_LEAKAGE"
    assert leakage_verdict(0.99) == "INFLATED_SUSPECTED_LEAKAGE"

def test_target_derivation(tmp_path):
    csv_path = tmp_path / "data.csv"
    df = pd.DataFrame({
        "Days for shipping (real)": [2, 5, "NaN", 4],
        "Days for shipment (scheduled)": [3, 4, 3, 4],
        GROUP_COLUMN: [1, 2, 3, 4]
    })
    df.to_csv(csv_path, index=False)
    
    res = build_frame(csv_path)
    assert len(res) == 3
    assert list(res["is_late"]) == [0, 1, 0]
