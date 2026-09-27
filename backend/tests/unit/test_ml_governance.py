"""Task 13: champion-guard rule, PSI, and drift flags (pure logic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nexafreight.services.ml_governance import (
    champion_decision,
    champion_self_check,
    drift_flags,
    mean_test_pinball,
    psi,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _meta(pinballs: tuple[float, float, float] | None) -> dict:
    if pinballs is None:
        return {"metrics": {"test": {}}}
    p10, p50, p85 = pinballs
    return {
        "metrics": {
            "test": {
                "p10": {"pinball_loss": p10},
                "p50": {"pinball_loss": p50},
                "p85": {"pinball_loss": p85},
            }
        }
    }


def test_mean_pinball_complete_and_incomplete() -> None:
    assert mean_test_pinball(_meta((1.0, 2.0, 3.0))) == 2.0
    assert mean_test_pinball(_meta(None)) is None
    assert mean_test_pinball({}) is None


def test_champion_guard_promotes_only_on_margin() -> None:
    champ = _meta((1.0, 1.0, 1.0))  # mean 1.0
    # 0.99 mean = 1% better -> promote (>= 0.5%)
    assert champion_decision(champ, _meta((0.99, 0.99, 0.99)))["decision"] == "promote"
    # 0.998 mean = 0.2% better -> keep (margin not met)
    assert champion_decision(champ, _meta((0.998, 0.998, 0.998)))["decision"] == "keep"
    # worse challenger -> keep, with reason
    out = champion_decision(champ, _meta((1.1, 1.1, 1.1)))
    assert out["decision"] == "keep" and "does not beat" in out["reason"]


def test_champion_guard_edge_paths() -> None:
    # first model: no champion
    assert champion_decision(None, _meta((1.0, 1.0, 1.0)))["decision"] == "promote"
    # incomplete challenger never promotes
    assert champion_decision(champion_decision and _meta((1.0, 1.0, 1.0)), _meta(None))[
        "decision"
    ] == "keep"
    # broken champion metadata: well-formed challenger takes over
    assert champion_decision({"metrics": {}}, _meta((1.0, 1.0, 1.0)))["decision"] == "promote"
    # degenerate champion (<= 0) never flips
    assert champion_decision(_meta((0.0, 0.0, 0.0)), _meta((0.5, 0.5, 0.5)))["decision"] == "keep"


def test_psi_identical_vs_disjoint_and_nan_safe() -> None:
    assert psi([1.0] * 100, [1.0] * 100) == 0.0
    assert psi([1.0] * 100, [2.0] * 100) > 3.0
    # NaNs must be ignored, not poison the result
    a = [1.0] * 50 + [float("nan")] * 50
    assert psi(a, [1.0] * 100) == 0.0


def test_drift_flags_freshness_and_rows() -> None:
    fresh_meta = {"trained_at": (NOW - timedelta(days=2)).isoformat()}
    out = drift_flags(fresh_meta, {}, now=NOW, expected_rows=100, current_rows=101)
    assert out["ok"] and out["flags"] == []

    stale_meta = {"trained_at": (NOW - timedelta(days=40)).isoformat()}
    out = drift_flags(stale_meta, {}, now=NOW)
    assert not out["ok"] and any(f.startswith("artifact_age") for f in out["flags"])

    out = drift_flags(fresh_meta, {}, now=NOW, expected_rows=100, current_rows=200)
    assert any(f.startswith("training_data_changed") for f in out["flags"])

    out = drift_flags({"trained_at": "garbage"}, {}, now=NOW)
    assert any("unparseable" in f for f in out["flags"])


def test_champion_self_check_on_committed_artifact() -> None:
    """Live integrity check against the committed champion (no training data)."""
    backend = Path(__file__).resolve().parents[2]
    models_dir = backend / "models" / "eta_quantile"
    processed = backend / "data" / "processed"
    import pytest

    if not (models_dir / "model.joblib").exists():
        pytest.skip("champion artifact not present")
    if not (processed / "test.parquet").exists():
        pytest.skip("processed parquets not in this checkout (data is gitignored)")
    out = champion_self_check(models_dir, processed)
    assert out["ok"], out
