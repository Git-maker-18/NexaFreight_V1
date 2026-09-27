import argparse
import sys
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, average_precision_score, brier_score_loss

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from nexafreight.eval.delay_benchmark import (
    build_frame,
    group_split,
    preprocess,
    calibration_table,
    leakage_verdict,
    PRE_SHIPMENT_ALLOWLIST,
    LEAK_COLUMNS,
    GROUP_COLUMN
)

def evaluate_model(y_true, y_pred, y_prob):
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob))
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, default="backend/data/raw/dataco/DataCoSupplyChain.csv")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--skip-lgbm", action="store_true")
    args = ap.parse_args()
    
    repo_root = Path(__file__).resolve().parent.parent.parent
    if args.synthetic:
        print("REPORT > Mode: SYNTHETIC")
        # generate 2000 rows
        n_rows = 2000
        n_orders = 400
        rng = np.random.default_rng(42)
        orders = rng.choice(np.arange(n_orders), size=n_rows)
        
        # We need days for shipping and days scheduled to create target
        # Let's inject a signal using "Order Item Quantity"
        qty = rng.integers(1, 10, size=n_rows)
        # base scheduled 3 days
        sched = np.full(n_rows, 3)
        # real days = 3 + (1 if qty > 5 else 0) + noise
        noise = rng.choice([0, 1, -1], size=n_rows)
        real = sched + (qty > 5).astype(int) + noise
        
        df = pd.DataFrame({
            GROUP_COLUMN: orders,
            "Days for shipment (scheduled)": sched,
            "Days for shipping (real)": real,
            "Order Item Quantity": qty,
            "Type": rng.choice(["DEBIT", "TRANSFER", "CASH"], size=n_rows),
            "Shipping Mode": rng.choice(["Standard Class", "First Class"], size=n_rows),
            "Late_delivery_risk": (real > sched).astype(int), # leak column present
            "Delivery Status": rng.choice(["Late delivery", "Advance shipping"], size=n_rows) # leak
        })
        
        for c in PRE_SHIPMENT_ALLOWLIST:
            if c not in df.columns:
                df[c] = rng.random(n_rows)
                
        csv_path = Path("/tmp/synthetic_dataco.csv") if sys.platform != "win32" else Path("synthetic_dataco.csv")
        df.to_csv(csv_path, index=False)
    else:
        csv_path = repo_root / args.csv
        if not csv_path.exists():
            print(f"ERROR: {csv_path} not found.")
            print("Please download the DataCo Smart Supply Chain dataset from Kaggle and place it there.")
            sys.exit(3)
        print(f"REPORT > Mode: REAL DATA ({csv_path})")

    # hash the file
    with open(csv_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()[:16]

    df_full = build_frame(csv_path)
    train_df, val_df, test_df = group_split(df_full, seed=42)
    
    X_train, X_val, X_test = preprocess(train_df, val_df, test_df)
    y_train = train_df["is_late"].values
    y_val = val_df["is_late"].values
    y_test = test_df["is_late"].values
    
    # M0: majority
    majority_class = int(np.bincount(y_train).argmax())
    y_pred_m0 = np.full_like(y_test, majority_class)
    y_prob_m0 = np.full_like(y_test, np.mean(y_train), dtype=float)
    
    # M1: rate
    y_prob_m1 = np.full_like(y_test, np.mean(y_train), dtype=float)
    y_pred_m1 = (y_prob_m1 >= 0.5).astype(int)
    
    # M2: logistic
    m2 = LogisticRegression(max_iter=1000)
    m2.fit(X_train, y_train)
    y_prob_m2 = m2.predict_proba(X_test)[:, 1]
    y_pred_m2 = m2.predict(X_test)
    
    models = {
        "M0_majority": evaluate_model(y_test, y_pred_m0, y_prob_m0),
        "M1_rate": evaluate_model(y_test, y_pred_m1, y_prob_m1),
        "M2_logistic": evaluate_model(y_test, y_pred_m2, y_prob_m2)
    }
    y_probs = {
        "M0_majority": y_prob_m0,
        "M1_rate": y_prob_m1,
        "M2_logistic": y_prob_m2
    }
    
    if not args.skip_lgbm:
        import lightgbm as lgb
        dtrain = lgb.Dataset(X_train, y_train)
        dval = lgb.Dataset(X_val, y_val, reference=dtrain)
        
        m3 = lgb.train(
            {"objective": "binary", "metric": "auc", "verbosity": -1},
            dtrain,
            num_boost_round=100,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(10, verbose=False)]
        )
        y_prob_m3 = m3.predict(X_test)
        y_pred_m3 = (y_prob_m3 >= 0.5).astype(int)
        models["M3_lgbm"] = evaluate_model(y_test, y_pred_m3, y_prob_m3)
        y_probs["M3_lgbm"] = y_prob_m3
        
    best_name = max(models.keys(), key=lambda k: models[k]["roc_auc"])
    best_roc_auc = models[best_name]["roc_auc"]
    
    cal_table = calibration_table(y_test, y_probs[best_name])
    verdict = leakage_verdict(best_roc_auc)
    
    artifact = {
        "dataset": {
            "path": str(csv_path),
            "sha256_first16": file_hash,
            "rows_total": len(df_full),
            "rows_scored": len(test_df),
            "late_rate": float(df_full["is_late"].mean()),
            "order_count": df_full[GROUP_COLUMN].nunique()
        },
        "split": {
            "seed": 42,
            "method": "GroupShuffle by Order Id",
            "train_orders": train_df[GROUP_COLUMN].nunique(),
            "train_rows": len(train_df),
            "val_orders": val_df[GROUP_COLUMN].nunique(),
            "val_rows": len(val_df),
            "test_orders": test_df[GROUP_COLUMN].nunique(),
            "test_rows": len(test_df),
        },
        "allowlist": PRE_SHIPMENT_ALLOWLIST,
        "leak_columns": LEAK_COLUMNS,
        "models": models,
        "best_model": best_name,
        "calibration": cal_table,
        "verdict": verdict,
        "leakage_reference_band": "0.978-0.993 (published; leakage-inflated)"
    }
    
    out_dir = Path(__file__).resolve().parent.parent / "eval" / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "delay_risk_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2)
        
    for m, metrics in models.items():
        print(f"REPORT > {m:12} ROC-AUC: {metrics['roc_auc']:.4f}  F1: {metrics['f1']:.4f}  PR-AUC: {metrics['pr_auc']:.4f}")
    
    print(f"REPORT > BEST MODEL: {best_name}")
    print(f"REPORT > VERDICT: {verdict}")
    print(f"REPORT > ARTIFACT SAVED TO: {out_path}")
    
    if verdict == "INFLATED_SUSPECTED_LEAKAGE":
        sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
