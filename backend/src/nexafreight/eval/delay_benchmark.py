import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.preprocessing import OneHotEncoder

PRE_SHIPMENT_ALLOWLIST = [
    "Type",
    "Days for shipment (scheduled)",
    "Shipping Mode",
    "Market",
    "Order Region",
    "Order Country",
    "Customer Segment",
    "Category Id",
    "Product Price",
    "Product Status",
    "Order Item Quantity",
    "Sales per customer",
    "Order Item Discount",
]

LEAK_COLUMNS = [
    "Late_delivery_risk",
    "Delivery Status",
    "Days for shipping (real)",
    "shipping date (DateOrders)",
    "Order Status",
]

GROUP_COLUMN = "Order Id"

def build_frame(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False, encoding="latin1")
    
    days_real = pd.to_numeric(df["Days for shipping (real)"], errors="coerce")
    days_sched = pd.to_numeric(df["Days for shipment (scheduled)"], errors="coerce")
    
    valid_mask = days_real.notna() & days_sched.notna()
    df = df[valid_mask].copy()
    
    # TARGET = derived: 1 if "Days for shipping (real)" > "Days for shipment (scheduled)" else 0
    df["is_late"] = (days_real[valid_mask] > days_sched[valid_mask]).astype(int)
    
    return df

def validate_features(columns: list[str]) -> list[str]:
    for col in columns:
        if col in LEAK_COLUMNS:
            raise ValueError(f"Leak column '{col}' is not allowed in features.")
        if col not in PRE_SHIPMENT_ALLOWLIST:
            raise ValueError(f"Unknown column '{col}' is not in PRE_SHIPMENT_ALLOWLIST.")
    return sorted(columns)

def group_split(df: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    unique_orders = np.sort(df[GROUP_COLUMN].unique())
    rng.shuffle(unique_orders)
    
    n = len(unique_orders)
    train_end = int(0.7 * n)
    val_end = int(0.85 * n)
    
    train_ids = unique_orders[:train_end]
    val_ids = unique_orders[train_end:val_end]
    test_ids = unique_orders[val_end:]
    
    assert len(set(train_ids).intersection(set(val_ids))) == 0
    assert len(set(val_ids).intersection(set(test_ids))) == 0
    assert len(set(train_ids).intersection(set(test_ids))) == 0
    
    train_df = df[df[GROUP_COLUMN].isin(train_ids)].copy()
    val_df = df[df[GROUP_COLUMN].isin(val_ids)].copy()
    test_df = df[df[GROUP_COLUMN].isin(test_ids)].copy()
    
    return train_df, val_df, test_df

def preprocess(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cols = [c for c in train.columns if c in PRE_SHIPMENT_ALLOWLIST]
    cols = validate_features(cols)
    
    cat_cols = [c for c in cols if train[c].dtype == object or str(train[c].dtype) == "category"]
    num_cols = [c for c in cols if c not in cat_cols]
    
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    if cat_cols:
        encoder.fit(train[cat_cols])
        
    def transform(df: pd.DataFrame) -> np.ndarray:
        arrays = []
        if num_cols:
            arrays.append(df[num_cols].to_numpy(dtype=float, na_value=0.0))
        if cat_cols:
            arrays.append(encoder.transform(df[cat_cols]))
            
        if arrays:
            return np.hstack(arrays)
        return np.empty((len(df), 0))
        
    return transform(train), transform(val), transform(test)

def calibration_table(y_true: np.ndarray, p_pred: np.ndarray, n_bins: int = 10) -> list[dict]:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    indices = np.digitize(p_pred, bins, right=True)
    
    table = []
    for i in range(1, n_bins + 1):
        mask = (indices == i)
        if i == 1:
            mask = mask | (p_pred == 0.0)
            
        count = int(np.sum(mask))
        mean_pred = float(np.mean(p_pred[mask])) if count > 0 else 0.0
        emp_rate = float(np.mean(y_true[mask])) if count > 0 else 0.0
            
        table.append({
            "bin": i,
            "bin_start": float(bins[i-1]),
            "bin_end": float(bins[i]),
            "count": count,
            "mean_predicted": mean_pred,
            "empirical_rate": emp_rate,
        })
    return table

def leakage_verdict(roc_auc: float) -> str:
    if roc_auc >= 0.97:
        return "INFLATED_SUSPECTED_LEAKAGE"
    return "OK"
