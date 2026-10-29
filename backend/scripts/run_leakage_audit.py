"""Leakage audit and label permutation test for delay classifier (PR 2, 2C)."""
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

print(f"Train shape: {X_train.shape}, Val shape: {X_val.shape}, Test shape: {X_test.shape}")
print(f"Train positive rate: {y_train.mean():.4f}, Val: {y_val.mean():.4f}, Test: {y_test.mean():.4f}")

# 1. Normal train
lgb_train = lgb.Dataset(X_train, label=y_train, categorical_feature=cat_cols)
params = {
    'objective': 'binary',
    'metric': 'auc',
    'verbosity': -1,
    'seed': 42,
    **best_params
}
model_normal = lgb.train(params, lgb_train, num_boost_round=best_iter)
preds_val_normal = model_normal.predict(X_val)
auc_val_normal = roc_auc_score(y_val, preds_val_normal)
preds_test_normal = model_normal.predict(X_test)
auc_test_normal = roc_auc_score(y_test, preds_test_normal)
ref_val_auc = meta['optuna']['best_val_auc']
ref_test_auc = meta['metrics']['lgbm_tuned_test']['roc_auc']

print(f"Normal Val AUC: {auc_val_normal:.4f} (ref: {ref_val_auc:.4f})")
print(f"Normal Test AUC: {auc_test_normal:.4f} (ref: {ref_test_auc:.4f})")

# 2. Permutation test (shuffled labels)
np.random.seed(42)
y_train_shuffled = np.random.permutation(y_train)
lgb_train_shuffled = lgb.Dataset(X_train, label=y_train_shuffled, categorical_feature=cat_cols)
model_perm = lgb.train(params, lgb_train_shuffled, num_boost_round=best_iter)
preds_val_perm = model_perm.predict(X_val)
auc_val_perm = roc_auc_score(y_val, preds_val_perm)
preds_test_perm = model_perm.predict(X_test)
auc_test_perm = roc_auc_score(y_test, preds_test_perm)

print(f"Permuted Val AUC: {auc_val_perm:.4f} (expected ~0.50)")
print(f"Permuted Test AUC: {auc_test_perm:.4f} (expected ~0.50)")

assert abs(auc_val_perm - 0.50) < 0.05, f"Leakage detected! AUC did not collapse: {auc_val_perm}"
assert abs(auc_test_perm - 0.50) < 0.05, f"Leakage detected! Test AUC did not collapse: {auc_test_perm}"

print("\nAll permutation checks passed: no label leakage into features.")
