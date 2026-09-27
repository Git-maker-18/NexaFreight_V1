# NexaFreight — Frozen Report (freeze-p2, 24 Sep 2026)

This report pins the numbers the paper claims. Generated at freeze;
regenerate gates with the commands below.

## Gates at freeze (operator machine, Windows, Python 3.11)

| Gate | Result |
|---|---|
| Unit suite | 538 passed, 2 skipped |
| Integration suite | 184 passed (183 + day-12b corridor fresh-clone test) |
| Validation matrix (CLI) | GREEN — 37/37 (30 static + 7 artifact) |
| Red Sea drill | GREEN — 1.700 / 1.735 / 1.246 (refs 1.72±0.15, 1.25±0.08) |
| Frontend | tsc clean; vitest 239 passed (19 files) |
| CI | backend pytest + validate + drill, frontend typecheck+vitest, all green |
| Alembic head | b7d4e2f8a6c1 |

## Key pinned values (traceable via eval/references.yaml)

- Corridor (searoute, neo-panamax): INJNP→NLRTM 6380/10848 nm (×1.70, +198.8 h);
  INMUN→NLRTM 6366/11045 nm (×1.735, +208.8 h); SGSIN→NLRTM 8383/10441 nm (×1.246, +84.0 h)
- Emission factors: sea 8.0 (GLEC band 7.6–9.1), rail 22.0, road 62.0, air 500.0 g/t-km
- Financial: SLA penalty 5%/day cap 10% (≈7× LD norms, documented multiplier);
  demurrage 4 free days, $62.5/day, ×2 after day 7; carbon price pinned $/kg
- Dwell p50 (h): INJNP 22, INMUN 18, INMAA 26, INVTZ 24 (±2); one-sided
  all-vessel bound 48.84 h (FY26) enforced
- ML (DataCo test split, committed artifacts): delay classifier accuracy 0.7313 /
  precision 0.7911 / Brier 0.2326; ETA pinball p10/p50/p85 = 0.1685/0.5054/0.2562
  (grouped-quantile p85 baseline 0.2080); champion raw_mono.test 0.9345,
  rearranged sanity 1.0
- Consolidation: ISO 668-derived capacity 28,000 kg / 33 m³ (SEA); cargo-class
  nominals documented as fallback

## Deterministic world (sandbox reference)

scripts/20 → parties: 9 (created 9); scripts/21 → itineraries=5 per order,
party/assignment determinism verified across rebuilds; 1,092 port_daily_stat
rows (SIMULATED); day-12d sea-leg geometry from searoute (JNPT→Rotterdam = 106
waypoints, 6380 nm — matches the corridor pin).

## Known issues at freeze (queued post-freeze)

1. **Legacy sea-EF parameter row.** A pre-GLEC ingest row
   (`co2.sea_g_per_tonne_km = 6.5`) persists in long-lived demo DBs; the
   pinned reference (8.0) governs all financial math and the gate. Regenerate
   parameter rows on the next world rebuild pass.
2. **Script 17 exit-2 semantics.** `17_build_congestion_climatology.py`
   exits 2 with "no PortDailyStat rows" on machines without the congestion
   world — graceful by design; not a failure.
3. **Rail/road leg geometry** remains the documented straight-line
   approximation (OSM rail-graph / ORS substitution = v2; see
   Real_Data_Pipeline_Map.md).
4. **Skips.** The 2 unit skips are artifact-dependent (parquet/model files
   gitignored) by design.

## Reproduce

    python -m pytest tests/unit -q
    python -m pytest tests/integration -q
    python eval/validate.py
    python scripts/24_red_sea_drill.py
    (frontend) npx tsc --noEmit && npx vitest run

Figures for the paper regenerate via the committed figure script against
the live validation service; see paper/README.md.
