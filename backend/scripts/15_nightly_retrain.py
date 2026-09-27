#!/usr/bin/env python3
"""Nightly retrain with champion guard (Task 13, P1). Thin CLI wrapper.

Two modes, chosen automatically:

Mode A (full retrain)  - when the joined DB+CSV training source has at least
  MIN_ROWS rows: backup champion -> train candidate (scripts/11) -> compare
  held-out mean pinball under the 0.5%-margin rule -> promote or restore.

Mode B (self-check)    - when training data is absent/insufficient (the
  normal case until the author-scale DB + full DataCo CSV are rebuilt):
  run services.ml_governance.champion_self_check — the committed artifact
  must load, serve through its own encode->predict->rearrange path, hold
  P10<=P50<=P85, and match its recorded monotonicity/schema/version.

Either mode writes eval/artifacts/retrain_report.json. Exit 0 = healthy
("keep"/"self-check ok" are healthy outcomes); 2 = infrastructure error.

Usage:
    PYTHONPATH=src python scripts/15_nightly_retrain.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "src"))

from nexafreight.services.ml_governance import (  # noqa: E402
    champion_decision,
    champion_self_check,
    mean_test_pinball,
)

CHAMPION_DIR = BACKEND / "models" / "eta_quantile"
BACKUP_DIR = BACKEND / "models" / "_champion_backup"
REPORT_PATH = BACKEND / "eval" / "artifacts" / "retrain_report.json"
PROCESSED = BACKEND / "data" / "processed"
MIN_ROWS = 10_000  # below this the join cannot train a serious challenger


def _load_meta(path: Path) -> dict | None:
    meta = path / "metadata.json"
    return json.loads(meta.read_text()) if meta.exists() else None


def _mode_a() -> tuple[str, dict]:
    champion_meta = _load_meta(CHAMPION_DIR)

    if CHAMPION_DIR.exists():
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        shutil.copytree(CHAMPION_DIR, BACKUP_DIR)

    result = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "11_train_eta_model.py")],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if BACKUP_DIR.exists():
            shutil.rmtree(CHAMPION_DIR, ignore_errors=True)
            shutil.copytree(BACKUP_DIR, CHAMPION_DIR)
        return "error", {"reason": "training failed; champion restored", "stderr_tail": result.stderr[-1500:]}

    candidate_meta = _load_meta(CHAMPION_DIR) or {}
    verdict = champion_decision(champion_meta, candidate_meta)

    if verdict["decision"] == "keep" and BACKUP_DIR.exists():
        shutil.rmtree(CHAMPION_DIR, ignore_errors=True)
        shutil.copytree(BACKUP_DIR, CHAMPION_DIR)
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)

    return verdict["decision"], {
        "champion_mean_pinball": mean_test_pinball(champion_meta or {}),
        "challenger_mean_pinball": mean_test_pinball(candidate_meta),
        "reason": verdict["reason"],
    }


def main() -> int:
    processed = PROCESSED
    missing = [f for f in ("train.parquet", "val.parquet", "test.parquet") if not (processed / f).exists()]
    if missing:
        print(f"missing processed training data {missing} — run scripts/09_build_training_data.py first")
        return 2

    # Mode selection: probe the joined training source size.
    from nexafreight.ml.data_source import load_raw

    try:
        rows = len(load_raw())
    except Exception as exc:  # no DB / no CSV -> Mode B
        print(f"training source unavailable ({exc.__class__.__name__}); Mode B")
        rows = 0

    if rows >= MIN_ROWS:
        mode = "A"
        print(f"Mode A: full retrain ({rows} source rows)")
        decision, details = _mode_a()
        healthy = decision in ("promote", "keep")
    else:
        mode = "B"
        print(f"Mode B: champion self-check (source rows {rows} < {MIN_ROWS})")
        check = champion_self_check(CHAMPION_DIR, processed)
        decision = "self_check_ok" if check["ok"] else "self_check_fail"
        details = {"checks": check["checks"], "served_rows": check.get("served_rows")}
        healthy = check["ok"]

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "source_rows": rows,
        "decision": decision,
        "healthy": healthy,
        **details,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print("RETRAIN:", "HEALTHY" if healthy else "UNHEALTHY")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
