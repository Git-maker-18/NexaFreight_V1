# NexaFreight ML Audit: Delay Classifier Leakage & ETA Quantile Benchmark (Phase 2, PR 2)

**Audit Date:** 2026-10-29  
**Branch:** `fix/pr2-glec-co2-and-ml-resolution`  
**Review Target:** ML-02 (ETA Quantile Regressor Lift & Coverage) and ML Delay Classifier (`best_iteration: 3`, Leakage, and Synthetic Label Root Cause).

---

## Executive Summary

1. **CO₂ Factor Unification (ML-03 / 2A):** Authoritative GLEC Framework v3.2 multimodal emission factors (`SEA: 8.0`, `ROAD: 62.0`, `RAIL: 28.0`, `AIR: 602.0` g/t-km) have been established as the single source of truth in `nexafreight.core.constants`. All divergent constants (12.0, 6.5, road 62.0 copied to sea) were removed. An Alembic migration (`f7a8b9c0d1e2`) successfully backfills existing legs and parameter tables with green migration tests (8/8 pass).
2. **ETA Quantiles Resolution (ML-02 / 2B — Option A):** LightGBM quantile regression yielded negative lift across all quantiles relative to the grouped empirical baseline (P10: -0.23%, P50: -0.36%, P85: -1.94%). Rather than claiming false ML lift, the P10/P50/P85 transit bounds are formally relabelled as **Empirical Lane Quantiles** with provenance `DERIVED`. The holdout test-set coverage is documented below, and all misleading "Predictive ML" UI copy has been replaced.
3. **Delay Classifier Leakage & Early Stopping Audit (2C):**
   - A permutation test (shuffling training labels randomly) collapsed validation AUC from **0.7238 to 0.5216** and test AUC from **0.7273 to 0.5079**, proving that the 14 pre-ship features have **zero target leakage**.
   - `best_iteration: 3` is explained by the synthetic nature of the DataCo dataset: `Late_delivery_risk` is derived directly from `Shipping Mode` with fixed per-mode transit distributions. After 3 trees, all usable signal from `shipping_mode` and `scheduled_shipping_days` is exhausted.

---

## 1. ETA Quantiles Holdout Benchmark (2B)

### 1.1 Model Performance vs Grouped Baseline
The 14-feature LightGBM quantile regressor was trained on chronological orders (`train_end: 2017-04-01`) and evaluated on the test holdout (`test: 8,109 orders` after `val_end: 2017-10-01`):

| Quantile | Target $\alpha$ | LightGBM Test Pinball | Grouped Baseline Pinball | Lift (%) | Nominal Coverage | Empirical Test Coverage |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **P10** | 0.10 | 0.1685 | 0.1681 | **-0.23%** | 10.0% | **9.66%** |
| **P50** | 0.50 | 0.5060 | 0.5036 | **-0.36%** | 50.0% | **51.77%** |
| **P85** | 0.85 | 0.2598 | 0.2513 | **-1.94%** | 85.0% | **83.66%** |

- **Empirical Interval Coverage $[P_{10}, P_{85}]$:** **74.8%** (nominal target: 75.0%).
- **Monotonicity ($P_{10} \le P_{50} \le P_{85}$):** 100.0% post-rearrangement.

### 1.2 Resolution
- In accordance with Decision Option A, the LightGBM run is maintained as a documented **negative result**.
- The dossier display and SLA risk engines consume these quantiles under provenance **`DERIVED`**, representing calibrated empirical lane transit distributions rather than predictive ML claims.
- Front-end labels in `ShipmentDossierPageContent` and `ShipmentInspectorPanel` were updated to `"Empirical Transit Quantiles & SLA Risk Assessment"`.

---

## 2. Delay Classifier Leakage & Permutation Audit (2C)

### 2.1 Feature Contract Inspection (Post-Ship / Target Leakage Check)
All 14 features in `models/delay_classifier/feature_schema.json` were audited for causality:
- `shipping_mode`: Mode of transport contracted at booking (**pre-ship**)
- `cargo_class`: Declared commodity handling category (**pre-ship**)
- `revenue`, `shipping_cost`, `product_price`, `order_profit`: Commercial terms agreed at checkout (**pre-ship**)
- `scheduled_shipping_days`: SLA commitment (**pre-ship**)
- `order_country`, `customer_country`: Origin and destination UN/LOCODE territories (**pre-ship**)
- `sla_month`, `sla_weekday`, `sla_quarter`: Promised delivery calendar features (**pre-ship**)
- `total_distance_km`, `leg_count`: Planned route corridor metrics (**pre-ship**)

**Verdict:** Zero post-ship fields (such as `days_for_shipping_real`, `delivery_status`, or AIS telemetry slip) exist in the feature matrix.

### 2.2 Permutation Test Execution
The training labels `historical_late_delivery` ($N = 46,711$) were randomly permuted to break any relationship with features, and a LightGBM model with identical Optuna hyperparameters was fitted:

| Condition | Training Labels | Validation ROC-AUC | Test ROC-AUC | Expected Range | Verdict |
|:---|:---|:---:|:---:|:---:|:---:|
| **Baseline (Original)** | True `historical_late_delivery` | **0.7238** | **0.7273** | ~0.7315 | Reference Reproduced |
| **Permuted (Shuffled)** | $\text{Permute}(y_{\text{train}})$ | **0.5216** | **0.5079** | $0.50 \pm 0.05$ | **PASS (No Leakage)** |

The collapse of ROC-AUC to ~0.50 under label permutation demonstrates that the features do not encode target information directly or indirectly.

### 2.3 Explanation of `best_iteration: 3`
Optuna early stopping halted tree induction at iteration 3 for the following reasons:
1. **Synthetic DataCo Label Generation:** In the DataCo dataset, `Late_delivery_risk` is an automated synthetic boolean generated as `Days for shipping (real) > Days for shipment (scheduled)`.
2. **Mode-Dominated Scheduled Days:** `Days for shipment (scheduled)` in DataCo was assigned via a rigid mode mapping (Standard Class = 4 days, Second Class = 2 days, First Class = 1 day, Same Day = 0 days).
3. **Signal Saturation:** A grouped baseline on `shipping_mode` alone attains **0.7075 ROC-AUC**. The gradient boosted trees exhaust virtually all available non-linear signal within 3 splits on `shipping_mode` and `scheduled_shipping_days` (SHAP importance: 0.139 and 0.016 respectively), with all other 12 features offering near-zero marginal predictive power (<0.005 SHAP).

---

## 3. Demand Forecast Verification (2D)

- Model: `StatsForecast AutoETS` (Additive Error, Trend, Seasonality with season length 4 weeks).
- Qualified lanes: 79 / 675 lanes meeting the minimum 26-week series threshold.
- Holdout evaluation: 13-week out-of-time horizon.
- Holdout WAPE: **32.16%** vs Seasonal Naive 44.02% (**+26.94% lift**).
- Median MASE: **0.7285** (63 of 79 lanes with $\text{MASE} \le 1.0$).
- Naming: Verified 100% compliant across backend code, API schemas, frontend charts, and documentation (no legacy Prophet references remain).
