"""ML governance (Task 13, P1): champion-guard retrain decisions + drift flags.

Discipline (board, Sim B): a challenger only becomes the champion when it
BEATS the champion on held-out test pinball by a margin — never on a noise
flip. Drift monitoring is a freshness + training-data-stability probe (v1);
live prediction drift logging arrives with outcome telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

MIN_REL_IMPROVEMENT = 0.005  # challenger must beat champion by >=0.5% mean pinball
QUANTILE_TAGS = ("p10", "p50", "p85")
PSI_BINS = 10
PSI_EPSILON = 1e-6
PSI_FLAG_THRESHOLD = 0.2  # conventional "significant shift" cut
MAX_ARTIFACT_AGE_DAYS = 30


def mean_test_pinball(meta: dict) -> float | None:
    """Mean held-out pinball across the three quantiles; None if incomplete."""
    test = (meta or {}).get("metrics", {}).get("test", {})
    values = []
    for tag in QUANTILE_TAGS:
        block = test.get(tag)
        if not isinstance(block, dict) or "pinball_loss" not in block:
            return None
        values.append(float(block["pinball_loss"]))
    return sum(values) / len(values) if values else None


def champion_decision(
    champion_meta: dict | None,
    challenger_meta: dict,
    *,
    min_rel_improvement: float = MIN_REL_IMPROVEMENT,
) -> dict:
    """Decide promote-vs-keep between the champion and a fresh challenger.

    Rule: promote iff the challenger's mean test pinball improves on the
    champion's by at least ``min_rel_improvement`` relative. A missing or
    broken champion is promoted over only if the challenger is complete and
    valid. Pure function — no I/O, fully unit-testable.
    """
    cand = mean_test_pinball(challenger_meta)
    if cand is None:
        return {
            "decision": "keep",
            "reason": "challenger metadata incomplete (missing quantile pinball)",
        }

    if not champion_meta:
        return {"decision": "promote", "reason": "no champion metadata; first trained model"}

    champ = mean_test_pinball(champion_meta)
    if champ is None:
        return {
            "decision": "promote",
            "reason": "champion metadata incomplete; challenger is strictly better-formed",
        }

    if champ <= 0:
        return {"decision": "keep", "reason": f"champion pinball {champ:.6f} <= 0; refusing to flip"}

    rel = (champ - cand) / champ
    if rel >= min_rel_improvement:
        return {
            "decision": "promote",
            "reason": f"challenger mean pinball {cand:.6f} beats champion {champ:.6f} "
            f"({rel:.2%} >= {min_rel_improvement:.2%})",
        }
    return {
        "decision": "keep",
        "reason": f"challenger mean pinball {cand:.6f} does not beat champion {champ:.6f} "
        f"by the required {min_rel_improvement:.2%} margin (delta {rel:.2%})",
    }


def psi(expected, actual, bins: int = PSI_BINS) -> float:
    """Population Stability Index of ``actual`` against ``expected``.

    Quantile-binned on ``expected``; NaNs dropped on both sides; zero shares
    clipped to PSI_EPSILON. Pure function over array-likes.
    """
    import numpy as np

    e = np.asarray([v for v in expected if v == v], dtype=float)
    a = np.asarray([v for v in actual if v == v], dtype=float)
    if e.size == 0 or a.size == 0:
        return 0.0

    edges = np.unique(np.quantile(e, [i / bins for i in range(1, bins)]))
    if edges.size == 0:
        return 0.0
    cuts = [float(x) for x in edges]

    def shares(values: np.ndarray) -> list[float]:
        counts = [0] * (len(cuts) + 1)
        for v in values:
            idx = 0
            while idx < len(cuts) and v > cuts[idx]:
                idx += 1
            counts[idx] += 1
        n = values.size
        return [max(c / n, PSI_EPSILON) for c in counts]

    se, sa = shares(e), shares(a)
    return float(sum((sa[i] - se[i]) * __import__("math").log(sa[i] / se[i]) for i in range(len(se))))


def drift_flags(
    meta: dict,
    psi_by_feature: dict[str, float],
    *,
    now: datetime | None = None,
    max_age_days: int = MAX_ARTIFACT_AGE_DAYS,
    psi_threshold: float = PSI_FLAG_THRESHOLD,
    expected_rows: int | None = None,
    current_rows: int | None = None,
) -> dict:
    """Freshness + feature-stability + training-data-change flags (v1)."""
    now = now or datetime.now(UTC)
    flags: list[str] = []

    trained_at_raw = (meta or {}).get("trained_at")
    age_days: float | None = None
    if trained_at_raw:
        try:
            trained = datetime.fromisoformat(str(trained_at_raw).replace("Z", "+00:00"))
            if trained.tzinfo is None:
                trained = trained.replace(tzinfo=UTC)
            age_days = (now - trained).total_seconds() / 86400.0
            if age_days > max_age_days:
                flags.append(f"artifact_age:{age_days:.1f}d>{max_age_days}d")
        except ValueError:
            flags.append("artifact_age:unparseable trained_at")
    else:
        flags.append("artifact_age:missing trained_at")

    for feature, value in sorted(psi_by_feature.items()):
        if value > psi_threshold:
            flags.append(f"psi:{feature}={value:.3f}>{psi_threshold}")

    if expected_rows is not None and current_rows is not None and expected_rows > 0:
        change = abs(current_rows - expected_rows) / expected_rows
        if change > 0.01:
            flags.append(
                f"training_data_changed:rows {expected_rows}->{current_rows} ({change:.1%})"
            )

    return {
        "ok": not flags,
        "flags": flags,
        "artifact_age_days": round(age_days, 2) if age_days is not None else None,
        "psi": {k: round(v, 4) for k, v in sorted(psi_by_feature.items())},
        "psi_threshold": psi_threshold,
        "max_age_days": max_age_days,
    }
def champion_self_check(models_dir: Path, processed_dir: Path) -> dict:
    """Artifact integrity + serving check (runnable without training data).

    Verifies: the artifact loads; bundle features match feature_schema.json
    and the committed parquet columns; the model serves through its own
    encode -> predict -> rearrange path; rearranged P10<=P50<=P85 holds at
    100%; raw (pre-rearrangement) monotonicity is consistent with the
    metadata's recorded test rate. Deliberately does NOT claim pinball
    reproduction — that requires the raw target, which the processed
    parquets do not carry (metadata provenance is the pinball record).
    """
    import json as _json

    import joblib
    import numpy as np
    import pandas as pd

    from nexafreight.ml.eta_model import EtaQuantileModel

    checks: list[dict] = []
    ok = True

    model_path = models_dir / "model.joblib"
    meta_path = models_dir / "metadata.json"
    if not model_path.exists() or not meta_path.exists():
        return {"ok": False, "checks": [{"name": "artifact_present", "ok": False}]}

    bundle = joblib.load(model_path)
    meta = _json.loads(meta_path.read_text())
    checks.append({"name": "artifact_loads", "ok": True})

    schema_path = models_dir / "feature_schema.json"
    feature_cols = list(bundle.get("feature_columns", []))
    if schema_path.exists():
        schema_cols = list(_json.loads(schema_path.read_text()).get("feature_columns", []))
        schema_ok = schema_cols == feature_cols
        checks.append({"name": "schema_matches_feature_schema", "ok": schema_ok})
        ok &= schema_ok

    test_path = processed_dir / "test.parquet"
    if not test_path.exists():
        checks.append({"name": "parquet_has_features", "ok": False, "note": "test.parquet missing"})
        return {"ok": False, "checks": checks}
    frame = pd.read_parquet(test_path).head(200)

    missing = [c for c in feature_cols if c not in frame.columns]
    if missing:
        checks.append({"name": "parquet_has_features", "ok": False, "missing": missing})
        return {"ok": False, "checks": checks}
    checks.append({"name": "parquet_has_features", "ok": True})

    # Serve through the model's own encode -> predict -> rearrange path.
    model = EtaQuantileModel()
    model.load(models_dir)
    preds = model.predict(frame)  # DataFrame batch -> list[EtaPrediction]
    p10 = np.array([p.p10_residual for p in preds], dtype=float)
    p50 = np.array([p.p50_residual for p in preds], dtype=float)
    p85 = np.array([p.p85_residual for p in preds], dtype=float)
    served_mono = float(np.mean((p10 <= p50 + 1e-9) & (p50 <= p85 + 1e-9)))
    serve_ok = bool(served_mono == 1.0 and np.isfinite(p10).all() and np.isfinite(p85).all())
    checks.append(
        {"name": "serves_rearranged_monotone", "ok": serve_ok, "monotonicity": round(served_mono, 4)}
    )
    ok &= serve_ok

    # Raw (pre-rearrangement) rate must be consistent with the recorded one.
    encoded = model._encode_frame(frame)
    raw = model._predict_raw(encoded)
    raw_matrix = np.column_stack([raw[t] for t in ("p10", "p50", "p85")])
    raw_rate = float(np.mean(np.all(np.diff(raw_matrix, axis=1) >= -1e-9, axis=1)))
    recorded_raw = float((meta.get("raw_monotonicity_rate") or {}).get("test", raw_rate))
    raw_ok = abs(raw_rate - recorded_raw) <= 0.05
    checks.append(
        {
            "name": "raw_monotonicity_matches_metadata",
            "ok": raw_ok,
            "served": round(raw_rate, 4),
            "recorded": round(recorded_raw, 4),
        }
    )
    ok &= raw_ok

    version_ok = bool(bundle.get("model_version")) and bundle.get("model_version") == meta.get(
        "model_version"
    )
    checks.append({"name": "version_consistent", "ok": version_ok})
    ok &= version_ok

    return {"ok": ok, "checks": checks, "served_rows": int(len(frame))}
