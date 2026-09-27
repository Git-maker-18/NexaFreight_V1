import pytest
import numpy as np
from nexafreight.eval.forecast_benchmark import (
    per_level_empirical_coverage,
    rmse,
    mase,
    pinball_loss
)
from nexafreight.ml.eta_model import pinball_loss as orig_pinball_loss

def test_coverage_identity():
    y_true = np.linspace(0, 1, 1000)
    pred = {
        0.10: np.full_like(y_true, 0.1),
        0.50: np.full_like(y_true, 0.5),
        0.85: np.full_like(y_true, 0.85)
    }
    cov = per_level_empirical_coverage(y_true, pred)
    assert abs(cov[0.10] - 0.10) < 0.02
    assert abs(cov[0.50] - 0.50) < 0.02
    assert abs(cov[0.85] - 0.85) < 0.02

def test_coverage_edge():
    y_true = np.array([1, 2, 3])
    pred = {0.5: np.array([4, 5, 6])}
    cov = per_level_empirical_coverage(y_true, pred)
    assert cov[0.5] == 1.0

def test_rmse_identity():
    y_true = np.array([3.0, -0.5, 2.0, 7.0])
    y_pred = np.array([2.5, 0.0, 2.0, 8.0])
    expected = np.sqrt(0.375)
    assert abs(rmse(y_true, y_pred) - expected) < 1e-6

def test_mase_identity():
    y_train = np.array([1, 2, 3, 4, 2, 4, 6, 8])
    y_test = np.array([10, 10])
    y_pred = np.array([7.5, 12.5])
    assert abs(mase(y_train, y_test, y_pred, 4) - 1.0) < 1e-6

def test_mase_perfect():
    y_train = np.array([1, 2, 3, 4, 2, 4, 6, 8])
    y_test = np.array([5, 6])
    y_pred = np.array([5, 6])
    assert mase(y_train, y_test, y_pred, 4) == 0.0

def test_mase_error_paths():
    with pytest.raises(ValueError, match="denominator is zero"):
        mase(np.array([1, 1, 1, 1, 1]), np.array([2]), np.array([3]), 2)
    with pytest.raises(ValueError, match="season_length"):
        mase(np.array([1, 2]), np.array([3]), np.array([4]), 0)
    with pytest.raises(ValueError, match="len"):
        mase(np.array([1, 2]), np.array([3]), np.array([4]), 2)

def test_pinball_import():
    assert pinball_loss is orig_pinball_loss

def test_per_level_dict_keys():
    cov = per_level_empirical_coverage(np.array([1]), {0.1: np.array([1]), 0.9: np.array([2])})
    assert set(cov.keys()) == {0.1, 0.9}
