# Paper package (task 24)

`main.tex` — the paper. `figures/` — generated from the live validation
service and measured artifacts (never hand-drawn numbers).

## Build

    cd paper
    pdflatex main && pdflatex main

(Overleaf: upload the `paper/` folder as-is. For JMSE / Future
Transportation, drop `main.tex` into their template — content is
self-contained and figures are referenced relatively.)

## Regenerate figures

From the repo root (backend deps installed, DB at head):

    PYTHONPATH=backend/src python3 scripts/fig_gen.py   # (or the day-13 patch's inline generator)

Figures are committed so the PDF builds without a DB; regeneration is
only needed after reference/gate changes — and any drift between a
regenerated figure and `eval/report.md` is itself a freeze violation.

## Provenance of every number

- Validation matrix counts: live service (`services/validation_matrix.py`)
- Corridor measurements: `scripts/23_seed_corridors.py` output (also the
  CI drill `scripts/24_red_sea_drill.py`)
- ML metrics: committed artifacts (`models/`), checked by artifact gates
- Financial constants: `eval/references.yaml` + `services/financial_engine.py`
- Gates: `eval/report.md` (frozen report)
