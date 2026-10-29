"""Recompute exact test-set pinball loss and lift for p10/p50/p85.
Also recompute test coverage from the serving code path.
Save output to evidence/pr2/pinball_recomputation_results.json.
"""
import sys
sys.path.insert(0, 'src')
import json
from pathlib import Path
import joblib
import pandas as pd
import numpy as np

from nexafreight.ml.constants import (
    FEATURE_COLUMNS,
    CATEGORICAL_COLUMNS,
    NUMERIC_COLUMNS,
    ETA_TARGET_COLUMN,
    TIME_AXIS_COLUMN,
    LABEL_COLUMN,
    SPLIT_DATES,
)
from nexafreight.ml.data_source import load_raw
from nexafreight.ml.eta_model import pinball_loss
from nexafreight.ml.features import build_features
from nexafreight.ml.feature_contract import encode_categorical_column, encode_frame

raw = load_raw()
actual = pd.to_numeric(raw['days_for_shipping_real'], errors='coerce')
sched = pd.to_numeric(raw['scheduled_shipping_days'], errors='coerce')
valid = (
    actual.notna()
    & sched.notna()
    & (actual >= 0)
    & (sched > 0)
    & raw[LABEL_COLUMN].notna()
)
raw = raw[valid].reset_index(drop=True)
actual = actual[valid].reset_index(drop=True)
sched = sched[valid].reset_index(drop=True)
y_all = (actual - sched).rename(ETA_TARGET_COLUMN).astype(float)

features_res = build_features(raw)
X_all = features_res[0] if isinstance(features_res, tuple) else features_res
X_all = X_all[list(FEATURE_COLUMNS)].copy()
for col in NUMERIC_COLUMNS:
    X_all[col] = pd.to_numeric(X_all[col], errors="coerce")

time_s = pd.to_datetime(raw[TIME_AXIS_COLUMN], errors="coerce", utc=True)
train_end = pd.Timestamp(SPLIT_DATES["train_end"], tz="UTC")
val_end = pd.Timestamp(SPLIT_DATES["val_end"], tz="UTC")

train_mask = time_s < train_end
val_mask = (time_s >= train_end) & (time_s < val_end)
test_mask = time_s >= val_end

X_train = X_all[train_mask].reset_index(drop=True)
y_train = y_all[train_mask].reset_index(drop=True)

X_val = X_all[val_mask].reset_index(drop=True)
y_val = y_all[val_mask].reset_index(drop=True)

X_test = X_all[test_mask].reset_index(drop=True)
y_test = y_all[test_mask].reset_index(drop=True)

art = joblib.load('models/eta_quantile/model.joblib')
feat_cols = art['feature_columns']
cat_cols = art['categorical_columns']
num_cols = art['numeric_columns']
cat_levels = art.get('category_levels', {})
boosters = art['models']

# Baseline predictions by shipping_mode
train_modes = X_train['shipping_mode'].astype(str).values
test_modes = X_test['shipping_mode'].astype(str).values

bl_preds = {}
base_quantiles = {}
for q in [0.10, 0.50, 0.85]:
    base_quantiles[q] = {}
    for m in np.unique(train_modes):
        mask = (train_modes == m)
        base_quantiles[q][m] = float(np.quantile(y_train[mask], q))
    bl_preds[q] = np.array([base_quantiles[q][m] for m in test_modes])

# Encode test features
X_test_encoded = encode_frame(
    X_test[feat_cols],
    feature_columns=feat_cols,
    cat_cols=cat_cols,
    num_cols=num_cols,
    cat_levels=cat_levels,
)

# Raw booster predictions
raw_preds = {
    'p10': boosters['p10'].predict(X_test_encoded),
    'p50': boosters['p50'].predict(X_test_encoded),
    'p85': boosters['p85'].predict(X_test_encoded),
}

# Monotonic sorted predictions
mat = np.column_stack([raw_preds['p10'], raw_preds['p50'], raw_preds['p85']])
sorted_mat = np.sort(mat, axis=1)
corr_preds = {
    'p10': sorted_mat[:, 0],
    'p50': sorted_mat[:, 1],
    'p85': sorted_mat[:, 2],
}

results = {"raw": {}, "corrected": {}, "baseline": {}}

print(f"Train rows: {len(X_train)}, Val rows: {len(X_val)}, Test rows: {len(X_test)}")
print("=== Recomputed Test-Set Pinball Loss & Lift ===")
for tag, q in [('p10', 0.10), ('p50', 0.50), ('p85', 0.85)]:
    bl_loss = float(pinball_loss(y_test, bl_preds[q], q))
    raw_loss = float(pinball_loss(y_test, raw_preds[tag], q))
    corr_loss = float(pinball_loss(y_test, corr_preds[tag], q))
    
    raw_lift = float((bl_loss - raw_loss) / bl_loss * 100.0)
    corr_lift = float((bl_loss - corr_loss) / bl_loss * 100.0)
    
    results["baseline"][tag] = round(bl_loss, 4)
    results["raw"][tag] = {"loss": round(raw_loss, 4), "lift_pct": round(raw_lift, 2)}
    results["corrected"][tag] = {"loss": round(corr_loss, 4), "lift_pct": round(corr_lift, 2)}
    
    print(f"\nQuantile {tag.upper()} (alpha={q}):")
    print(f"  Baseline Loss:           {bl_loss:.4f}")
    print(f"  Raw LightGBM Loss:       {raw_loss:.4f}  --> Lift: {raw_lift:+.2f}%")
    print(f"  Monotonic-Corrected Loss: {corr_loss:.4f}  --> Lift: {corr_lift:+.2f}%")

# Coverage analysis:
cov_empirical = {
    0.10: float(np.mean(y_test.values <= bl_preds[0.10])),
    0.50: float(np.mean(y_test.values <= bl_preds[0.50])),
    0.85: float(np.mean(y_test.values <= bl_preds[0.85])),
}
cov_raw_model = {
    0.10: float(np.mean(y_test.values <= raw_preds['p10'])),
    0.50: float(np.mean(y_test.values <= raw_preds['p50'])),
    0.85: float(np.mean(y_test.values <= raw_preds['p85'])),
}
cov_corr_model = {
    0.10: float(np.mean(y_test.values <= corr_preds['p10'])),
    0.50: float(np.mean(y_test.values <= corr_preds['p50'])),
    0.85: float(np.mean(y_test.values <= corr_preds['p85'])),
}

print("\n=== Test Coverage by Prediction Source ===")
print("Empirical Lane/Mode Quantiles (The Shipped Quantiles):")
for q, c in cov_empirical.items():
    print(f"  p{int(q*100)}: {c:.4f} ({c*100:.2f}%)")

print("LightGBM Monotonic-Corrected:")
for q, c in cov_corr_model.items():
    print(f"  p{int(q*100)}: {c:.4f} ({c*100:.2f}%)")

out = {
    "test_rows": len(X_test),
    "pinball_results": results,
    "empirical_shipped_quantiles": base_quantiles,
    "coverage": {
        "empirical_lane_quantiles": cov_empirical,
        "lightgbm_corrected": cov_corr_model,
        "lightgbm_raw": cov_raw_model,
    }
}

for dest in [Path('evidence/pr2/pinball_recomputation_results.json'), Path('../evidence/pr2/pinball_recomputation_results.json')]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))

print("\nSaved to evidence/pr2/pinball_recomputation_results.json")
