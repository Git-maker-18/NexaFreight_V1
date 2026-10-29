# NexaFreight Sealed Evaluation Metrics & Verified Benchmarks

*Published 29 Oct 2026. Sealed baseline for production deployment and technical reports.*

---

## 1. Delay Risk Classification Benchmark

Trained on chronological DataCo Smart Supply Chain order history (Train: 2015–2016, Test: 2017).

| Model / Feature Configuration | Test ROC-AUC | Lift over Mode Baseline | Verdict |
| :--- | :--- | :--- | :--- |
| **`scheduled_shipping_days` alone** | **0.7289** | +0.0194 | Primary predictor |
| **Full 14-Feature LightGBM Model** | **0.7273** | +0.0178 | Recovers synthetic rule |
| **`shipping_mode` alone** | **0.7095** | Baseline (0.0000) | Mode service proxy |
| **Model without Mode and Schedule** | **0.5007** | -0.2088 | Near-random guessing |

### Statistical Lift & Confidence Intervals
- **Full Model vs. `scheduled_shipping_days`**: Mean $\Delta \text{AUC} = -0.0016$ ($95\% \text{ Bootstrap CI}: [-0.0075, +0.0044]$).
- **Early Stopping**: Halts at iteration 3 (`best_iteration: 3`) because additional gradient boosted trees add zero incremental signal beyond the mode mapping.
- **Label Rate Cross-Tabulation**:
  - `AIR` (First Class / Same Day): **82.26%** late delivery rate ($n = 4,775$)
  - `RAIL` (Second Class): **76.81%** late delivery rate ($n = 6,214$)
  - `SEA` (Standard Class): **38.14%** late delivery rate ($n = 17,477$)

---

## 2. ETA Quantile Estimation ($p_{10}, p_{50}, p_{85}$)

### Negative Result: LightGBM Multi-Quantile Regression
Evaluated on holdout test set residuals (transit days):

| Quantile | Baseline Pinball Loss | LightGBM Pinball Loss | Relative Lift | Serving Decision |
| :--- | :--- | :--- | :--- | :--- |
| **$P_{10}$** | 0.1702 | 0.1706 | **-0.23%** | Rejected (negative lift) |
| **$P_{50}$** | 0.4958 | 0.5054 | **-1.94%** | Rejected (negative lift) |
| **$P_{85}$** | 0.2553 | 0.2562 | **-0.35%** | Rejected (negative lift) |

### Production Serving: Empirical Lane Quantiles
Served directly from `LANE_QUANTILES_TABLE` with provenance `DERIVED`:
- **AIR**: $[1, 1, 1]$ days
- **RAIL**: $[0, 2, 4]$ days
- **SEA**: $[-2, 0, 2]$ days
- **Test-Set Coverage**: $P_{10}: 32.85\%$, $P_{50}: 66.40\%$, $P_{85}: 100.00\%$ (exceeds nominal continuous percentiles because discrete integer thresholds capture full point-mass distributions).

---

## 3. Demand Forecasting Benchmark

- **Model**: `StatsForecast AutoETS` (Exponential Smoothing with automatic error, trend, and seasonal selection).
- **Holdout Horizon**: 12-week test split across 79 distinct commercial transport lanes.
- **Performance**:
  - **WAPE (Weighted Absolute Percentage Error)**: **32.16%**
  - **Lift over Seasonal-Naive Baseline**: **+26.9%**

---

## 4. Emissions Accounting

Emissions factors use GLEC default intensity factors (basis not independently verified), standardized across all routing, scoring, financial calculation, and reporting engines:

| Transport Mode | Default Factor (g CO2e / t-km) | Category Description |
| :--- | :--- | :--- |
| **AIR** | **602.0** | Air freight, long-haul twin-aisle |
| **ROAD** | **62.0** | Heavy articulated truck (>32t), ambient |
| **RAIL** | **22.0** | Continental electric/diesel mixed freight |
| **SEA** | **16.1** | Container ship, 8,000-14,999 TEU |

---

## 5. Test Suite & Verification Summary

| Suite / Check | Passing | Failing / xfail | Notes |
| :--- | :--- | :--- | :--- |
| **Backend Pytest** | **885 passed** | **5 xfailed** | 5 Pareto frontier benchmarks (ALG-01), 0 failures |
| **Backend Postgres Integration** | **179 passed** | **0 failed** | Full integration suite on PostgreSQL 16 |
| **Frontend Vitest** | **352 passed** | **0 failed** | Security, SSE tickets, UI, and logic unit tests |
| **Frontend Build** | **40 routes compiled** | **0 errors** | Static pages & API proxies verified |
| **Alembic Heads** | **1 head** | `a1b2c3d4e5f6` | Migration chain verified on SQLite & PG |
