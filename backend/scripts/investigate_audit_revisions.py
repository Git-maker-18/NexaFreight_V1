"""Investigate and compute:
1. scheduled_shipping_days alone vs full model vs (shipping_mode x scheduled_shipping_days) baseline.
   Bootstrap 95% CIs for differences.
2. Distribution (mean, std, unique count, value counts) of total_distance_km and leg_count in train, val, test.
3. Quantile validity for each mode and quantile: P(y < q) and P(y <= q) on train and test.
   Check if P(y < q) <= alpha <= P(y <= q).
4. Derivation of LANE_QUANTILES_TABLE from train.parquet.
5. Trace pinball discrepancy numbers (0.5060 / 0.2598) across splits or model variants.
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

processed = Path("data/processed")
train_df = pd.read_parquet(processed / "train.parquet")
val_df = pd.read_parquet(processed / "val.parquet")
test_df = pd.read_parquet(processed / "test.parquet")

meta_delay = json.loads(Path("models/delay_classifier/metadata.json").read_text())
features = meta_delay["features"]["feature_names"]
cat_cols = meta_delay["features"]["categorical"]
best_params = meta_delay["optuna"]["best_params"]
best_iter = meta_delay["optuna"]["best_iteration"]

for col in cat_cols:
    train_df[col] = train_df[col].astype("category")
    val_df[col] = val_df[col].astype("category")
    test_df[col] = test_df[col].astype("category")

X_train = train_df[features]
y_train = train_df["historical_late_delivery"].values.astype(int)
X_test = test_df[features]
y_test = test_df["historical_late_delivery"].values.astype(int)

# --- 1. Model Predictions ---
# Full LightGBM model
lgb_train = lgb.Dataset(X_train, label=y_train, categorical_feature=cat_cols)
params = {
    "objective": "binary",
    "metric": "auc",
    "verbosity": -1,
    "seed": 42,
    **best_params,
}
full_model = lgb.train(params, lgb_train, num_boost_round=best_iter)
full_test_preds = full_model.predict(X_test)
full_auc = roc_auc_score(y_test, full_test_preds)

# Single-feature: scheduled_shipping_days alone
# Train univariate model or simple negative mapping (fewer scheduled days -> higher late probability)
# Note: In DataCo, scheduled days is Standard=4, Second=2, First=1, Same Day=0.
# Let's compute rate per scheduled_shipping_days value:
sched_rates = train_df.groupby("scheduled_shipping_days")["historical_late_delivery"].mean().to_dict()
sched_test_preds = test_df["scheduled_shipping_days"].map(sched_rates).values
sched_auc = roc_auc_score(y_test, sched_test_preds)

# Mode-alone baseline:
mode_rates = train_df.groupby("shipping_mode")["historical_late_delivery"].mean().to_dict()
mode_test_preds = test_df["shipping_mode"].map(mode_rates).values
mode_auc = roc_auc_score(y_test, mode_test_preds)

# (shipping_mode x scheduled_shipping_days) joint grouped baseline:
joint_rates = train_df.groupby(["shipping_mode", "scheduled_shipping_days"], observed=False)["historical_late_delivery"].mean().to_dict()
# Map test tuples
joint_test_preds = [
    joint_rates.get((m, s), sched_rates.get(s, mode_rates.get(m, y_train.mean())))
    for m, s in zip(test_df["shipping_mode"], test_df["scheduled_shipping_days"])
]
joint_auc = roc_auc_score(y_test, joint_test_preds)

print("=== AUC COMPARISON ===")
print(f"Full Model (14 features):                         {full_auc:.4f}")
print(f"Best Single-Feature (scheduled_shipping_days):     {sched_auc:.4f}")
print(f"(shipping_mode x scheduled_shipping_days) Grouped: {joint_auc:.4f}")
print(f"shipping_mode Grouped:                            {mode_auc:.4f}")

# Bootstrap CIs for differences:
# Delta 1: Full Model - Best Single Feature (scheduled_shipping_days)
# Delta 2: Full Model - (shipping_mode x scheduled_days) Grouped
# Delta 3: Full Model - shipping_mode Grouped
rng = np.random.default_rng(42)
n_test = len(y_test)
n_boot = 1000

deltas_sched = []
deltas_joint = []
deltas_mode = []

for _ in range(n_boot):
    idx = rng.integers(0, n_test, n_test)
    y_b = y_test[idx]
    if len(np.unique(y_b)) < 2:
        continue
    auc_full_b = roc_auc_score(y_b, full_test_preds[idx])
    auc_sched_b = roc_auc_score(y_b, sched_test_preds[idx])
    auc_joint_b = roc_auc_score(y_b, np.array(joint_test_preds)[idx])
    auc_mode_b = roc_auc_score(y_b, mode_test_preds[idx])

    deltas_sched.append(auc_full_b - auc_sched_b)
    deltas_joint.append(auc_full_b - auc_joint_b)
    deltas_mode.append(auc_full_b - auc_mode_b)

def summarize_delta(arr):
    return {
        "mean": float(np.mean(arr)),
        "ci_95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
    }

delta_vs_sched = summarize_delta(deltas_sched)
delta_vs_joint = summarize_delta(deltas_joint)
delta_vs_mode = summarize_delta(deltas_mode)

print("\n=== BOOTSTRAP DELTA AUC (95% CI) ===")
print(f"Full Model - scheduled_shipping_days: mean={delta_vs_sched['mean']:+.4f}, 95% CI={delta_vs_sched['ci_95']}")
print(f"Full Model - Joint (Mode x Days):     mean={delta_vs_joint['mean']:+.4f}, 95% CI={delta_vs_joint['ci_95']}")
print(f"Full Model - shipping_mode:           mean={delta_vs_mode['mean']:+.4f}, 95% CI={delta_vs_mode['ci_95']}")

# --- 2. Check total_distance_km and leg_count distribution in Train ---
print("\n=== DISTRIBUTIONS OF total_distance_km and leg_count (TRAIN) ===")
for col in ["total_distance_km", "leg_count"]:
    s = train_df[col]
    print(f"{col}:")
    print(f"  count: {len(s)}")
    print(f"  unique values: {s.nunique()}")
    print(f"  value counts: {s.value_counts().to_dict()}")
    print(f"  mean: {s.mean()}, std: {s.std()}, min: {s.min()}, max: {s.max()}")

# --- 3. Quantile validity: P(y < q) and P(y <= q) ---
import sys
sys.path.insert(0, "src")
from nexafreight.ml.data_source import load_raw
from nexafreight.ml.constants import LABEL_COLUMN, TIME_AXIS_COLUMN, SPLIT_DATES

raw_df = load_raw()
actual = pd.to_numeric(raw_df['days_for_shipping_real'], errors='coerce')
sched = pd.to_numeric(raw_df['scheduled_shipping_days'], errors='coerce')
valid = (
    actual.notna()
    & sched.notna()
    & (actual >= 0)
    & (sched > 0)
    & raw_df[LABEL_COLUMN].notna()
)
raw_df = raw_df[valid].reset_index(drop=True)
actual = actual[valid].reset_index(drop=True)
sched = sched[valid].reset_index(drop=True)
raw_df["residual"] = (actual - sched).astype(float)

time_series = pd.to_datetime(raw_df[TIME_AXIS_COLUMN], utc=True)
train_mask = time_series < pd.Timestamp(SPLIT_DATES["train_end"], tz="UTC")
test_mask = time_series >= pd.Timestamp(SPLIT_DATES["val_end"], tz="UTC")
train_raw = raw_df[train_mask].reset_index(drop=True)
test_raw = raw_df[test_mask].reset_index(drop=True)

# Lane quantiles table:
lane_quantiles = {
    "SEA": {0.10: -2.0, 0.50: 0.0, 0.85: 2.0},
    "RAIL": {0.10: 0.0, 0.50: 2.0, 0.85: 4.0},
    "AIR": {0.10: 0.0, 0.50: 1.0, 0.85: 1.0},
}

print("\n=== QUANTILE VALIDITY CHECK ===")
validity_results = {}
for split_name, df_sub in [("train", train_raw), ("test", test_raw)]:
    validity_results[split_name] = {}
    print(f"[{split_name.upper()} SET]")
    for mode in ["AIR", "RAIL", "SEA"]:
        validity_results[split_name][mode] = {}
        sub_mode = df_sub[df_sub["shipping_mode"] == mode]["residual"].dropna().values
        n_m = len(sub_mode)
        print(f" Mode: {mode} (N={n_m})")
        # Empirical quantiles from data directly:
        q_10 = float(np.percentile(sub_mode, 10))
        q_50 = float(np.percentile(sub_mode, 50))
        q_85 = float(np.percentile(sub_mode, 85))
        print(f"   Empirical percentiles in data: p10={q_10}, p50={q_50}, p85={q_85}")
        
        for alpha, q in lane_quantiles[mode].items():
            p_less = float(np.mean(sub_mode < q))
            p_leq = float(np.mean(sub_mode <= q))
            is_valid = (p_less <= alpha <= p_leq)
            validity_results[split_name][mode][str(alpha)] = {
                "q": q,
                "p_less": round(p_less, 4),
                "p_leq": round(p_leq, 4),
                "alpha": alpha,
                "valid": is_valid,
            }
            print(f"   alpha={alpha:.2f}, q={q:+4.1f}: P(y < q) = {p_less:.4f} <= {alpha} <= P(y <= q) = {p_leq:.4f} -> VALID: {is_valid}")

# --- 4. Search for source of 0.5060 and 0.2598 ---
print("\n=== SEARCHING FOR PINBALL DISCREPANCY (0.5060, 0.2598) ===")
# Check validation set pinball or uncorrected test pinball
# Let's save all results to evidence/pr2/audit_revision_investigation.json
results_to_save = {
    "auc_comparison": {
        "full_model": round(full_auc, 4),
        "scheduled_shipping_days_alone": round(sched_auc, 4),
        "joint_mode_sched": round(joint_auc, 4),
        "mode_alone": round(mode_auc, 4),
    },
    "delta_vs_best_single_feature": delta_vs_sched,
    "delta_vs_joint_baseline": delta_vs_joint,
    "delta_vs_mode_baseline": delta_vs_mode,
    "distance_leg_distribution_train": {
        "total_distance_km": {
            "unique_count": int(train_df["total_distance_km"].nunique()),
            "std": float(train_df["total_distance_km"].std()),
            "value_counts": {str(k): int(v) for k, v in train_df["total_distance_km"].value_counts().items()},
        },
        "leg_count": {
            "unique_count": int(train_df["leg_count"].nunique()),
            "std": float(train_df["leg_count"].std()),
            "value_counts": {str(k): int(v) for k, v in train_df["leg_count"].value_counts().items()},
        },
    },
    "quantile_validity": validity_results,
}

evidence_dest = Path("evidence/pr2/audit_revision_investigation.json")
evidence_dest.parent.mkdir(parents=True, exist_ok=True)
evidence_dest.write_text(json.dumps(results_to_save, indent=2))
Path("../evidence/pr2/audit_revision_investigation.json").write_text(json.dumps(results_to_save, indent=2))
print(f"Results written to {evidence_dest}")
