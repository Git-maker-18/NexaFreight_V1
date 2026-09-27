"""Validation matrix (Task 17, P1): ONE implementation of the reference
checks, consumed by BOTH `eval/validate.py` (CLI gate) and the public
`GET /api/health/validation` endpoint that feeds the /validation page.

Extracted verbatim from validate.py's static + artifact layers so the CLI,
the API, and the page can never disagree. The CLI keeps its exact stdout
format; the API adds machine-readable rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_BACKEND = Path(__file__).resolve().parents[3]
_REFS_PATH = _BACKEND / "eval" / "references.yaml"


def load_references() -> dict[str, Any]:
    return yaml.safe_load(_REFS_PATH.read_text())


def _row(name: str, actual: float, ref: float, tol: float) -> dict[str, Any]:
    return {
        "name": name,
        "actual": round(float(actual), 6),
        "ref": ref,
        "tol": tol,
        "ok": bool(abs(float(actual) - float(ref)) <= tol),
    }


def build_static_matrix(refs: dict[str, Any]) -> list[dict[str, Any]]:
    """The static layer: registry + engine constants vs references.yaml."""
    from nexafreight.core.params import FALLBACK_DEFAULTS
    from nexafreight.services.financial_engine import (
        CO2_G_PER_T_KM,
        DEMURRAGE_DAILY_RATE,
        FREIGHT_RATE_PER_T_KM,
        SLA_PENALTY_PCT_PER_WEEK,
    )
    from nexafreight.services.insurance import (
        INSURED_VALUE_UPLIFT,
        INSURANCE_PCT_BY_MODE,
    )

    def r(key: str) -> dict[str, Any]:
        return refs[key]

    fx = FALLBACK_DEFAULTS["fx.usd_inr"]
    rows: list[dict[str, Any]] = [
        _row("fx.usd_inr", fx, r("fx_usd_inr")["value"], r("fx_usd_inr")["check"]["abs"]),
        _row("freight AIR $/tkm", FREIGHT_RATE_PER_T_KM["AIR"], r("freight_air_usd_per_tkm")["value"], r("freight_air_usd_per_tkm")["check"]["abs"]),
        _row("freight ROAD INR/tkm", FREIGHT_RATE_PER_T_KM["ROAD"] * fx, r("freight_road_inr_per_tkm")["value"], r("freight_road_inr_per_tkm")["check"]["abs"]),
        _row("freight RAIL INR/tkm", FREIGHT_RATE_PER_T_KM["RAIL"] * fx, r("freight_rail_inr_per_tkm")["value"], r("freight_rail_inr_per_tkm")["check"]["abs"]),
        _row("freight SEA $/tkm", FREIGHT_RATE_PER_T_KM["SEA"], r("freight_sea_usd_per_tkm")["value"], r("freight_sea_usd_per_tkm")["check"]["abs"]),
        _row("demurrage INR/box/day", DEMURRAGE_DAILY_RATE * fx, r("demurrage_inr_per_box_day")["value"], r("demurrage_inr_per_box_day")["check"]["abs"]),
        _row("demurrage free days", FALLBACK_DEFAULTS["demurrage.free_days"], r("demurrage_free_days")["value"], r("demurrage_free_days")["check"]["abs"]),
        _row("SLA penalty %/week", FALLBACK_DEFAULTS["sla.penalty_pct_per_week"], r("sla_penalty_pct_per_week")["value"], r("sla_penalty_pct_per_week")["check"]["abs"]),
        _row("SLA penalty per week (fraction)", SLA_PENALTY_PCT_PER_WEEK, 0.005, 0.001),
        _row("SLA cap %", FALLBACK_DEFAULTS["sla.penalty_cap_pct"], r("sla_penalty_cap_pct")["value"], r("sla_penalty_cap_pct")["check"]["abs"]),
        _row("road speed expressway", FALLBACK_DEFAULTS["road.speed.expressway"], r("road_speed_expressway_kmph")["value"], r("road_speed_expressway_kmph")["check"]["abs"]),
        _row("road speed city/state", FALLBACK_DEFAULTS["road.speed.state_highway"], r("road_speed_artificial_city_kmph")["value"], r("road_speed_artificial_city_kmph")["check"]["abs"]),
        _row("insurance ocean", INSURANCE_PCT_BY_MODE["SEA"], r("insurance_pct_sea")["value"], r("insurance_pct_sea")["check"]["abs"]),
        _row("insurance air", INSURANCE_PCT_BY_MODE["AIR"], r("insurance_pct_air")["value"], r("insurance_pct_air")["check"]["abs"]),
        _row("insurance uplift", INSURED_VALUE_UPLIFT, r("insurance_uplift")["value"], r("insurance_uplift")["check"]["abs"]),
        _row("sea CO2 EF g/tkm", CO2_G_PER_T_KM["SEA"], r("sea_co2_ef_g_per_tkm")["value"], r("sea_co2_ef_g_per_tkm")["check"]["abs"]),
        _row("carbon price $/kg", FALLBACK_DEFAULTS["carbon.price_usd_per_kg"], r("carbon_price_usd_per_kg")["value"], r("carbon_price_usd_per_kg")["check"]["abs"]),
        _row("congestion tier warn", FALLBACK_DEFAULTS["disruption.congestion.ratio_warn"], refs["disruption_congestion_tiers"]["warn"]["value"], refs["disruption_congestion_tiers"]["warn"]["check"]["abs"]),
        _row("congestion tier critical", FALLBACK_DEFAULTS["disruption.congestion.ratio_critical"], refs["disruption_congestion_tiers"]["critical"]["value"], refs["disruption_congestion_tiers"]["critical"]["check"]["abs"]),
    ]

    # Dwell block (C8/C9): per-port pins + tail ratio + one-sided bound.
    dwell_refs = {k: v for k, v in refs["port_dwell_p50_hours"].items() if isinstance(v, dict)}
    worst_ratio_dev = 0.0
    for locode in sorted(dwell_refs):
        dref = dwell_refs[locode]
        p50 = FALLBACK_DEFAULTS[f"port.dwell.p50.{locode}"]
        rows.append(_row(f"dwell p50 {locode}", p50, dref["value"], dref["check"]["abs"]))
        worst_ratio_dev = max(
            worst_ratio_dev,
            abs(FALLBACK_DEFAULTS[f"port.dwell.p90_ext.{locode}"] / p50 - refs["port_dwell_p90_ratio"]["value"]),
        )
    rows.append(_row("dwell p90/p50 ratio dev from 2.0", worst_ratio_dev, 0.0, refs["port_dwell_p90_ratio"]["check"]["abs"]))
    bound = refs["port_dwell_allvessel_upper_h"]["value"]
    worst_dwell = max(FALLBACK_DEFAULTS[f"port.dwell.p50.{k}"] for k in dwell_refs)
    rows.append(
        {
            "name": "dwell p50 max <= India all-vessel",
            "actual": round(float(worst_dwell), 6),
            "ref": bound,
            "tol": 0.0,
            "ok": bool(worst_dwell <= bound),
            "one_sided": True,
        }
    )
    return rows


def build_artifact_matrix(refs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The artifact layer: ETA metadata + Red Sea drill when present.

    Returns (rows, skips) — skips are human-readable SKIP reasons.
    """
    import json as _json

    rows: list[dict[str, Any]] = []
    skips: list[str] = []

    meta_path = _BACKEND / "models" / "eta_quantile" / "metadata.json"
    if meta_path.exists():
        meta = _json.loads(meta_path.read_text())
        m = meta["metrics"]["test"]
        ref = refs["ml_baselines_dataco"]["eta_sea_inclusive_test_pinball"]
        for tag in ("p10", "p50", "p85"):
            rows.append(_row(f"{tag} pinball", m[tag]["pinball_loss"], ref[tag], 0.01))
        schema = _json.loads((meta_path.parent / "feature_schema.json").read_text())
        levels = schema.get("categorical_levels", {}).get("shipping_mode", [])
        has_sea = {"AIR", "RAIL", "SEA"} <= set(levels)
        rows.append({"name": f"ETA artifact shipping_mode levels {levels}", "actual": 1.0 if has_sea else 0.0, "ref": 1.0, "tol": 0.0, "ok": has_sea})
    else:
        skips.append("ETA artifact metadata not found")

    drill_path = _BACKEND / "eval" / "artifacts" / "red_sea_drill.json"
    if drill_path.exists():
        drill = _json.loads(drill_path.read_text())
        groups = {"INJNP->NLRTM": "india_eu", "INMUN->NLRTM": "india_eu", "SGSIN->NLRTM": "singapore_eu"}
        for lane, group in groups.items():
            cref = refs[f"cape_diversion_ratio_{group}"]
            rows.append(_row(f"cape ratio {lane}", drill["results"][lane]["ratio"], cref["value"], cref["check"]["abs"]))
    else:
        skips.append("Red Sea drill artifact not found (run scripts/24 --json)")

    return rows, skips


def build_matrix() -> dict[str, Any]:
    """Full matrix for the API/page: static + artifact layers, all rows."""
    refs = load_references()
    static = build_static_matrix(refs)
    artifact, skips = build_artifact_matrix(refs)
    all_rows = static + artifact
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "all_ok": all(r["ok"] for r in all_rows),
        "pass_count": sum(1 for r in all_rows if r["ok"]),
        "total_count": len(all_rows),
        "static": static,
        "artifact": artifact,
        "skips": skips,
    }
