"""Forecast benchmark instruments (wave 3b)."""
import numpy as np

# D1. Reuse pinball_loss
from nexafreight.ml.eta_model import pinball_loss

def per_level_empirical_coverage(y_true: np.ndarray, pred_by_level: dict[float, np.ndarray]) -> dict[float, float]:
    """
    coverage(level q) = mean(y_true <= pred_q).
    Must return one entry per requested level.
    """
    coverage = {}
    for level, preds in pred_by_level.items():
        coverage[level] = float(np.mean(y_true <= preds))
    return coverage

def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

def mase(y_train: np.ndarray, y_test: np.ndarray, y_pred: np.ndarray, season_length: int) -> float:
    """
    denominator = mean(|y_train[t] - y_train[t - season_length]|) over the in-sample one-step seasonal naive ON TRAIN ONLY.
    Raise ValueError if the denominator is zero or if season_length < 1 or len(y_train) <= season_length.
    """
    if season_length < 1:
        raise ValueError("season_length must be >= 1")
    if len(y_train) <= season_length:
        raise ValueError("len(y_train) must be > season_length")
    
    naive_diffs = np.abs(y_train[season_length:] - y_train[:-season_length])
    denom = np.mean(naive_diffs)
    
    if denom == 0.0:
        raise ValueError("denominator is zero")
        
    numerator = np.mean(np.abs(y_test - y_pred))
    return float(numerator / denom)
