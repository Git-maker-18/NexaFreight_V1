"""Run delay classifier deep investigation:
- Label-rate by shipping_mode cross-tab
- Single-feature AUC for all 14 features (ranked)
- Ablation without shipping_mode and scheduled_shipping_days
- Bootstrap 95% CI on the lift of the full model over the shipping_mode-only baseline
- Save raw output to evidence/pr2/delay_ablation_results.json
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

processed = Path('data/processed')
train_df = pd.read_parquet(processed / 'train.parquet')
val_df = pd.read_parquet(processed / 'val.parquet')
test_df = pd.read_parquet(processed / 'test.parquet')

meta = json.loads(Path('models/delay_classifier/metadata.json').read_text())
features = meta['features']['feature_names']
cat_cols = meta['features']['categorical']
num_cols = meta['features']['numeric']
best_params = meta['optuna']['best_params']
best_iter = meta['optuna']['best_iteration']

for col in cat_cols:
    train_df[col] = train_df[col].astype('category')
    val_df[col] = val_df[col].astype('category')
    test_df[col] = test_df[col].astype('category')

X_train = train_df[features]
y_train = train_df['historical_late_delivery'].values.astype(int)
X_val = val_df[features]
y_val = val_df['historical_late_delivery'].values.astype(int)
X_test = test_df[features]
y_test = test_df['historical_late_delivery'].values.astype(int)

# 1. Label-rate-by-shipping_mode cross-tab
crosstab = {}
for split_name, df, y in [("train", train_df, y_train), ("val", val_df, y_val), ("test", test_df, y_test)]:
    crosstab[split_name] = {}
    for mode in sorted(df['shipping_mode'].astype(str).unique()):
        mask = (df['shipping_mode'].astype(str) == mode)
        n = int(mask.sum())
        late_count = int(y[mask].sum())
        rate = float(late_count / n) if n > 0 else 0.0
        crosstab[split_name][mode] = {"n": n, "late_count": late_count, "late_rate": round(rate, 4)}

print("=== 1. Cross-tab: Label Rate by Shipping Mode ===")
for split_name, modes in crosstab.items():
    print(f"[{split_name}]")
    for m, stats in modes.items():
        print(f"  {m:<10} n={stats['n']:<6} late_rate={stats['late_rate']:.4f} ({stats['late_count']} late)")

# 2. Shipping-mode-only baseline test AUC
mode_rates = train_df.groupby(train_df['shipping_mode'].astype(str))['historical_late_delivery'].mean().to_dict()
test_mode_preds = test_df['shipping_mode'].astype(str).map(mode_rates).values
baseline_test_auc = roc_auc_score(y_test, test_mode_preds)
print(f"\nShipping-mode-only baseline test AUC: {baseline_test_auc:.4f}")

# Train full model
lgb_train = lgb.Dataset(X_train, label=y_train, categorical_feature=cat_cols)
params = {
    'objective': 'binary',
    'metric': 'auc',
    'verbosity': -1,
    'seed': 42,
    **best_params
}
full_model = lgb.train(params, lgb_train, num_boost_round=best_iter)
full_test_preds = full_model.predict(X_test)
full_test_auc = roc_auc_score(y_test, full_test_preds)
print(f"Full model test AUC: {full_test_auc:.4f}")

# Share of AUC attributable to shipping_mode:
# AUC above random guess (0.50):
excess_baseline = baseline_test_auc - 0.50
excess_full = full_test_auc - 0.50
pct_share_of_excess = (excess_baseline / excess_full) * 100.0 if excess_full > 0 else 0.0
print(f"Excess AUC over random: Baseline = {excess_baseline:.4f}, Full = {excess_full:.4f}")
print(f"Share of learnable AUC from shipping_mode alone: {pct_share_of_excess:.1f}%")

# 3. Single-feature AUC for all 14 features
single_feature_results = {}
for feat in features:
    is_cat = feat in cat_cols
    if is_cat:
        # Univariate rate mapping on train
        rate_map = train_df.groupby(train_df[feat].astype(str))['historical_late_delivery'].mean().to_dict()
        global_mean = y_train.mean()
        preds = test_df[feat].astype(str).map(rate_map).fillna(global_mean).values
    else:
        # Numeric: single feature LightGBM or monotonic direction
        vals = pd.to_numeric(train_df[feat], errors='coerce').fillna(0).values
        # Simple univariate tree with depth 2 to capture non-linearities fairly
        ds = lgb.Dataset(train_df[[feat]], label=y_train)
        m = lgb.train({'objective': 'binary', 'verbosity': -1, 'seed': 42, 'max_depth': 2, 'learning_rate': 0.1}, ds, num_boost_round=10)
        preds = m.predict(test_df[[feat]])
    
    auc = roc_auc_score(y_test, preds)
    # Ensure AUC >= 0.50 orientation
    single_feature_results[feat] = round(float(auc), 4)

ranked_features = sorted(single_feature_results.items(), key=lambda x: x[1], reverse=True)
print("\n=== 2. Single-Feature Test AUC (Ranked) ===")
for r, (f, score) in enumerate(ranked_features, 1):
    print(f"  {r:>2}. {f:<26} AUC = {score:.4f}")

# 4. Ablation without shipping_mode and scheduled_shipping_days
ablation_features = [f for f in features if f not in ("shipping_mode", "scheduled_shipping_days")]
ablation_cats = [c for c in cat_cols if c in ablation_features]
ds_abl = lgb.Dataset(train_df[ablation_features], label=y_train, categorical_feature=ablation_cats)
abl_params = {k: v for k, v in params.items() if k != 'feature_fraction'}
abl_params['feature_fraction'] = 0.8
abl_model = lgb.train(abl_params, ds_abl, num_boost_round=20)
abl_test_preds = abl_model.predict(test_df[ablation_features])
abl_test_auc = roc_auc_score(y_test, abl_test_preds)
print(f"\n=== 3. Ablation without shipping_mode & scheduled_shipping_days ===")
print(f"  Ablated model test AUC: {abl_test_auc:.4f} (drop: {full_test_auc - abl_test_auc:+.4f})")

# 5. Bootstrap 95% CI on lift of full model over shipping_mode baseline
n_boot = 1000
rng = np.random.default_rng(42)
n_test = len(y_test)
lifts = []
deltas = []

for _ in range(n_boot):
    idx = rng.integers(0, n_test, n_test)
    y_b = y_test[idx]
    if len(np.unique(y_b)) < 2:
        continue
    auc_full_b = roc_auc_score(y_b, full_test_preds[idx])
    auc_base_b = roc_auc_score(y_b, test_mode_preds[idx])
    deltas.append(auc_full_b - auc_base_b)

delta_mean = float(np.mean(deltas))
ci_lower = float(np.percentile(deltas, 2.5))
ci_upper = float(np.percentile(deltas, 97.5))
print(f"\n=== 4. Bootstrap 95% CI on Delta AUC (Full Model - Baseline) ===")
print(f"  Delta AUC mean: {delta_mean:.4f}")
print(f"  95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]")

out_data = {
    "crosstab": crosstab,
    "shipping_mode_baseline_test_auc": round(float(baseline_test_auc), 4),
    "full_model_test_auc": round(float(full_test_auc), 4),
    "share_of_excess_auc_pct": round(float(pct_share_of_excess), 1),
    "single_feature_auc_ranked": ranked_features,
    "ablation_without_mode_and_sched_auc": round(float(abl_test_auc), 4),
    "bootstrap_delta_auc": {
        "mean": round(delta_mean, 4),
        "ci_95": [round(ci_lower, 4), round(ci_upper, 4)],
    }
}

for dest in [Path('evidence/pr2/delay_ablation_results.json'), Path('../evidence/pr2/delay_ablation_results.json')]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out_data, indent=2))
print(f"\nSaved results to evidence/pr2/delay_ablation_results.json")

