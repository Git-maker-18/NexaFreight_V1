#!/usr/bin/env python3
"""Red Sea replay drill (Task 16). Thin CLI wrapper over
nexafreight.services.red_sea_drill. Ratios must stay inside the bands
pinned in eval/references.yaml (cape_diversion_ratio_*); exit 1 on breach.

Usage:
    PYTHONPATH=src python scripts/24_red_sea_drill.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml  # noqa: E402

from nexafreight.services.red_sea_drill import LANE_GROUP, measure_ratios  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="write eval/artifacts/red_sea_drill.json")
    args = ap.parse_args()

    refs = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "eval" / "references.yaml").read_text()
    )
    measured = measure_ratios()

    print("== Red Sea replay: Suez vs Cape (neo-panamax, live marine graph) ==")
    ok = True
    results: dict[str, dict] = {}
    for lane, m in measured.items():
        ref = refs[f"cape_diversion_ratio_{LANE_GROUP[lane]}"]
        lo, hi = ref["value"] - ref["check"]["abs"], ref["value"] + ref["check"]["abs"]
        lane_ok = lo <= m["ratio"] <= hi
        ok &= lane_ok
        results[lane] = {**m, "ref": ref["value"], "tol": ref["check"]["abs"], "pass": lane_ok}
        print(
            f"  [{'PASS' if lane_ok else 'FAIL'}] {lane:14} suez {m['suez_nm']:6.0f} nm -> "
            f"cape {m['cape_nm']:6.0f} nm  ratio {m['ratio']:.3f} "
            f"(ref {ref['value']:.2f} +-{ref['check']['abs']:.2f}, +{m['added_hours']:.1f} h)"
        )

    if args.json:
        artifact_dir = Path(__file__).resolve().parent.parent / "eval" / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "tool": "searoute marine graph",
            "results": results,
        }
        (artifact_dir / "red_sea_drill.json").write_text(json.dumps(payload, indent=2))
        print("artifact written: eval/artifacts/red_sea_drill.json")

    print("RED SEA DRILL:", "GREEN" if ok else "BREACH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
