#!/usr/bin/env python3
"""Drift monitor (Task 13, P1). Thin CLI wrapper over services.ml_governance.

v1 honest scope — three probes:
  1. artifact freshness (trained_at age vs 30-day budget)
  2. data-integrity vs the PREVIOUS drift report: per-feature train-parquet
     means must not move >5% between runs (a bad/corrupted rebuild trips
     this instantly; a stable pipeline never does). Split PSI is reported
     INFORMATION-ONLY: with a time-based split, train-vs-test distribution
     gaps are structural, not drift.
  3. row-count change vs the previous report (>1% flags the champion as
     stale relative to the data -> recommend retrain)

Exit 1 when any flag fires; the report lands in
eval/artifacts/drift_report.json and becomes the next run's baseline.

Usage:
    PYTHONPATH=src python scripts/16_drift_monitor.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "src"))

import pandas as pd  # noqa: E402

from nexafreight.services.ml_governance import drift_flags, psi  # noqa: E402

CHAMPION_DIR = BACKEND / "models" / "eta_quantile"
PROCESSED = BACKEND / "data" / "processed"
REPORT_PATH = BACKEND / "eval" / "artifacts" / "drift_report.json"
MEAN_SHIFT_FLAG = 0.05  # relative mean move between consecutive runs
PSI_FEATURES_MAX = 6
MEAN_SKIP = {"label", "target", "days_late"}


def main() -> int:
    meta_path = CHAMPION_DIR / "metadata.json"
    if not meta_path.exists():
        print("no champion artifact (models/eta_quantile/metadata.json missing)")
        return 2
    meta = json.loads(meta_path.read_text())

    missing = [f for f in ("train.parquet", "test.parquet") if not (PROCESSED / f).exists()]
    if missing:
        print(f"missing processed data {missing} — run scripts/09_build_training_data.py first")
        return 2
    train = pd.read_parquet(PROCESSED / "train.parquet")
    test = pd.read_parquet(PROCESSED / "test.parquet")

    numeric = [
        c
        for c in train.columns
        if pd.api.types.is_numeric_dtype(train[c])
        and c in test.columns
        and c.lower() not in MEAN_SKIP
    ]
    probe = numeric[:6]

    prev: dict = {}
    if REPORT_PATH.exists():
        try:
            prev = json.loads(REPORT_PATH.read_text())
        except json.JSONDecodeError:
            prev = {}

    # Probe 2: mean-shift vs previous report (baseline on first run).
    means_now = {c: float(train[c].mean()) for c in probe}
    shift_flags: list[str] = []
    for col, mean_now in means_now.items():
        prev_mean = (prev.get("train_means") or {}).get(col)
        if prev_mean is None or prev_mean == 0:
            continue
        if abs(mean_now - prev_mean) / abs(prev_mean) > MEAN_SHIFT_FLAG:
            shift_flags.append(f"data_shift:{col} {prev_mean:.3f}->{mean_now:.3f}")

    # Split PSI: information only (structural under a time split).
    psi_info = {c: round(psi(train[c], test[c]), 4) for c in probe}

    report = drift_flags(
        meta,
        {},  # PSI intentionally not flagging; reported as info
        expected_rows=prev.get("train_rows"),
        current_rows=int(len(train)),
    )
    report["flags"] = shift_flags + [f for f in report["flags"]]
    report["ok"] = not report["flags"]
    report["generated_at"] = datetime.now(UTC).isoformat()
    report["train_rows"] = int(len(train))
    report["train_means"] = means_now
    report["split_psi_info"] = psi_info

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))

    print("== Drift monitor ==")
    print(f"  artifact age: {report['artifact_age_days']} d (budget {report['max_age_days']} d)")
    print(f"  train rows: {report['train_rows']}" + (f" (previous: {prev.get('train_rows')})" if prev.get("train_rows") else " (baseline run)"))
    print("  split PSI (info):", {k: report['split_psi_info'][k] for k in list(report['split_psi_info'])[:3]}, "...")
    if report["flags"]:
        print("  FLAGS:", "; ".join(report["flags"]))
    print("DRIFT:", "CLEAN" if report["ok"] else "FLAGGED")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
