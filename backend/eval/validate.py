#!/usr/bin/env python3
"""Validate the project's numbers against published external references.

Task 9 (eval harness). Rule: evaluation is against PUBLICLY available
research/reports/benchmarks — never the project against itself.

Layers:
  static (default) — params registry + engine constants + artifacts metadata
                     must match eval/references.yaml within tolerance.
  --live           — additionally re-verify searoute distances (needs network
                     + searoute) and the golden road duration (needs repo deps).

Exit code 0 = all green; 1 = any drift. Designed to become the CI gate
(Task_Rankings #17) and the paper's numbers-backstop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml  # noqa: E402


def _load_references() -> dict:
    ref_path = Path(__file__).resolve().parent / "references.yaml"
    return yaml.safe_load(ref_path.read_text())


def _check(name: str, actual: float, expected: float, tol: float) -> bool:
    ok = abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name:<44} actual={actual:<12} ref={expected} (±{tol})")
    return ok


def validate_static(refs: dict) -> bool:
    """Static layer via the shared matrix service (Task 17: one implementation
    for the CLI gate and the /api/health/validation endpoint)."""
    from nexafreight.services.validation_matrix import build_static_matrix

    rows = build_static_matrix(refs)
    ok = True
    print("== Static layer: registry + engine constants vs references ==")
    for row in rows:
        status = "PASS" if row["ok"] else "FAIL"
        ok &= row["ok"]
        actual = row["actual"] if isinstance(row.get("actual"), float) else row["actual"]
        print(f"  [{status}] {row['name']:<44} actual={actual:<12} ref={row['ref']} (\u00b1{row['tol']})")
    return bool(ok)


def validate_artifact(refs: dict) -> bool:
    """Artifact layer via the shared matrix service."""
    from nexafreight.services.validation_matrix import build_artifact_matrix

    rows, skips = build_artifact_matrix(refs)
    ok = True
    eta_rows = [r for r in rows if "pinball" in r["name"] or "shipping_mode" in r["name"]]
    cape_rows = [r for r in rows if "cape ratio" in r["name"]]
    if eta_rows:
        print("== Artifact layer: ETA test pinball vs reproduced references ==")
        for row in eta_rows:
            status = "PASS" if row["ok"] else "FAIL"
            ok &= row["ok"]
            print(f"  [{status}] {row['name']:<44} actual={row['actual']:<12} ref={row['ref']} (\u00b1{row['tol']})")
    if cape_rows:
        print("== Artifact layer: Red Sea replay ratios vs pinned bands ==")
        for row in cape_rows:
            status = "PASS" if row["ok"] else "FAIL"
            ok &= row["ok"]
            print(f"  [{status}] {row['name']:<44} actual={row['actual']:<12} ref={row['ref']} (\u00b1{row['tol']})")
    for skip in skips:
        print(f"  [SKIP] {skip}")
    return bool(ok)


def _make_stdout_safe() -> None:
    """Never crash on console encoding (Windows cp1252 cannot print e.g. ₹).

    Reconfigure stdout to replace unencodable characters instead of raising.
    """
    try:
        sys.stdout.reconfigure(errors="replace")  # Python 3.7+
    except (AttributeError, ValueError):
        pass


def main() -> int:
    _make_stdout_safe()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="also verify searoute distances (network)")
    args = ap.parse_args()

    refs = _load_references()
    ok = validate_static(refs)
    ok &= validate_artifact(refs)
    if args.live:
        ok &= validate_live(refs)
    print("\nVALIDATION:", "GREEN — all numbers trace to published references" if ok else "RED — drift detected")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
