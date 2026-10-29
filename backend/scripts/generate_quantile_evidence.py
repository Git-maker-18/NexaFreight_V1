"""Generate exact tables for:
1. Quantile validity: P(y < q) and P(y <= q) for each mode and quantile on Train and Test.
2. Search for the origin of 0.5060 and 0.2598.
"""
import sys
sys.path.insert(0, "src")
import json
from pathlib import Path
import numpy as np
import pandas as pd

from nexafreight.ml.constants import SPLIT_DATES, TIME_AXIS_COLUMN, LABEL_COLUMN
from nexafreight.ml.data_source import load_raw
from nexafreight.ml.features import build_features
from nexafreight.ml.eta_model import pinball_loss

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
raw = raw[valid].copy().reset_index(drop=True)
actual = actual[valid].reset_index(drop=True)
sched = sched[valid].reset_index(drop=True)
raw["residual"] = (actual - sched).astype(float)

time_s = pd.to_datetime(raw[TIME_AXIS_COLUMN], utc=True)
train_end = pd.Timestamp(SPLIT_DATES["train_end"], tz="UTC")
val_end = pd.Timestamp(SPLIT_DATES["val_end"], tz="UTC")

train_mask = time_s < train_end
val_mask = (time_s >= train_end) & (time_s < val_end)
test_mask = time_s >= val_end

splits = {
    "train": raw[train_mask].reset_index(drop=True),
    "val": raw[val_mask].reset_index(drop=True),
    "test": raw[test_mask].reset_index(drop=True),
}

lane_quantiles = {
    "AIR": {"0.10": 1.0, "0.50": 1.0, "0.85": 1.0},
    "RAIL": {"0.10": 0.0, "0.50": 2.0, "0.85": 4.0},
    "SEA": {"0.10": -2.0, "0.50": 0.0, "0.85": 2.0},
}

validity_table = {}

print("=== QUANTILE VALIDITY TABLE: P(y < q) <= alpha <= P(y <= q) ===")
for split_name in ["train", "test"]:
    validity_table[split_name] = {}
    print(f"\n--- {split_name.upper()} SET ---")
    df_s = splits[split_name]
    for mode in ["AIR", "RAIL", "SEA"]:
        validity_table[split_name][mode] = {}
        sub_y = df_s[df_s["shipping_mode"] == mode]["residual"].values
        n = len(sub_y)
        print(f"Mode {mode} (N = {n}):")
        for alpha_str, q in lane_quantiles[mode].items():
            alpha = float(alpha_str)
            p_less = float(np.mean(sub_y < q))
            p_leq = float(np.mean(sub_y <= q))
            is_valid = (p_less <= alpha <= p_leq)
            validity_table[split_name][mode][alpha_str] = {
                "q": q,
                "alpha": alpha,
                "p_less": round(p_less, 4),
                "p_leq": round(p_leq, 4),
                "valid": is_valid,
                "n": n,
            }
            print(f"  alpha={alpha:.2f}, q={q:+4.1f}: P(y < q)={p_less:.4f} <= {alpha:.2f} <= P(y <= q)={p_leq:.4f}  [VALID: {is_valid}]")

# Search for origin of 0.5060 and 0.2598:
print("\n=== SEARCHING FOR 0.5060 and 0.2598 ===")
# Check metadata.json in models/eta_quantile
meta_eta = json.loads(Path("models/eta_quantile/metadata.json").read_text())
print("metadata.json metrics:")
for split, d in meta_eta["metrics"].items():
    print(f"  [{split}]")
    for q_tag, vals in d.items():
        print(f"    {q_tag}: {vals}")

# Save results
out_file = Path("evidence/pr2/quantile_validity_results.json")
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps(validity_table, indent=2))
Path("../evidence/pr2/quantile_validity_results.json").write_text(json.dumps(validity_table, indent=2))
print(f"\nSaved to {out_file}")
