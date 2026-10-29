# NexaFreight ML Audit: Delay Classifier Leakage & ETA Quantile Benchmark (Phase 2, PR 2)

**Audit Date:** 2026-10-29  
**Branch:** `fix/pr2-glec-co2-and-ml-resolution`  
**Review Target:** ML-02 (ETA Quantile Regressor Lift & Empirical Lane Quantiles) and Delay Classifier (`best_iteration: 3`, Synthetic Label Recovery, Single-Feature AUC, Feature Ablation, and Pipeline Sanity).

---

## Executive Summary

1. **CO₂ Factor Unification (ML-03 / 2A):**
   Authoritative GLEC Framework v3.2 multimodal emission factors (`SEA: 8.0`, `ROAD: 62.0`, `RAIL: 28.0`, `AIR: 602.0` g/t-km) have been established as the single source of truth in `nexafreight.core.constants`. All divergent runtime constants (e.g., 12.0, 6.5, road 62.0 copied to sea) were removed. Alembic data migration `f7a8b9c0d1e2` backfills existing legs and parameter tables with comprehensive migration tests passing (8/8).

2. **ETA Quantiles Resolution (ML-02 / 2B — Option A):**
   LightGBM quantile regression yielded negative lift against the grouped empirical baseline across all three quantiles (P10: -0.23%, P50: -0.36%, P85: -1.94%). Rather than claiming false ML lift, the P10/P50/P85 transit bounds are formally relabelled as **Empirical Lane Quantiles** with provenance **`DERIVED`**. Serving code in `/api/predict/eta` and `/api/shipments/{id}/predict` has been refactored to serve directly from the calibrated lane-quantiles lookup table (`LANE_QUANTILES_TABLE`) and verified with proof tests never to load `model.joblib`. The LightGBM training artifacts are archived in `backend/eval/` as a documented negative result.

3. **Delay Classifier Dynamics & Synthetic Labelling (2C):**
   - **Headline Finding:** ~92.2% of the classifier's excess AUC over random (and >97% of learnable signal) is derived from `shipping_mode` and `scheduled_shipping_days` alone. The model predominantly recovers DataCo's deterministic synthetic labelling rule rather than learning genuine real-world delay dynamics. AUC (~0.727) does not indicate real-world operational delay predictability.
   - **Ablation Collapse:** Ablating `shipping_mode` and `scheduled_shipping_days` causes test ROC-AUC to collapse completely from **0.7273 to 0.5007** (near-random guessing). The remaining 12 pre-ship features contain virtually zero independent predictive signal.
   - **Bootstrap 95% Confidence Interval:** The delta AUC between the full 14-feature LightGBM model and the simple grouped `shipping_mode` baseline is small but positive: mean **+0.0178** (95% CI: `[0.0105, 0.0254]`).
   - **LightGBM Early Stopping:** Tree induction terminated at iteration 3 (`best_iteration: 3`) because LightGBM early stopping detected that validation loss ceased improving once the mode-to-late-rate mapping was captured.
   - **Permutation Test Clarification:** The label permutation experiment is documented strictly as a **pipeline sanity check** (confirming that gradient boosting converges to random guessing ~0.50 AUC under independent random labels). It cannot detect feature leakage (which was independently checked via codebase audits and causality checks).

---

## 1. ETA Quantiles Holdout Benchmark & Serving Resolution (2B)

### 1.1 Pinball Loss Recomputation & Discrepancy Resolution

The 14-feature LightGBM quantile regressor was trained on chronological orders (`train_end: 2017-04-01`) and evaluated on the out-of-time test holdout (`8,109` orders after `val_end: 2017-10-01`).

Raw predictions and monotonically rearranged predictions were recomputed directly against test observations ($y = \text{days\_for\_shipping\_real} - \text{scheduled\_shipping\_days}$). Results are saved in `evidence/pr2/pinball_recomputation_results.json`:

| Quantile | Target $\alpha$ | Baseline Pinball | Raw LightGBM Pinball | Monotonic Corrected Pinball | Monotonic Lift (%) | Quoted in `metadata.json` | Old Report Table Discrepancy |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **P10** | 0.10 | **0.1681** | 0.1686 (-0.33%) | **0.1685** | **-0.23%** | 0.1685 (-0.23%) | Matched (0.1685) |
| **P50** | 0.50 | **0.5036** | 0.5053 (-0.35%) | **0.5054** | **-0.36%** | 0.5054 (-0.36%) | Discrepancy (old report had 0.5060) |
| **P85** | 0.85 | **0.2513** | 0.2568 (-2.18%) | **0.2562** | **-1.94%** | 0.2562 (-1.94%) | Discrepancy (old report had 0.2598) |

**Explanation of Old Report Discrepancy:**
In preliminary drafts of `eval/report.md`, intermediate uncorrected loss figures (0.5060 for P50 and 0.2598 for P85) were copied into the markdown table while retaining the post-tuning lift percentages (-0.36% and -1.94%). Calculating lift directly from 0.5060 vs baseline 0.5036 yields $-0.48\%$, and from 0.2598 vs 0.2513 yields $-3.38\%$. As verified in `models/eta_quantile/metadata.json` and recomputed from raw test predictions, the true evaluated pinball losses are **0.5054** for P50 (lift: -0.36%) and **0.2562** for P85 (lift: -1.94%).

### 1.2 Discrete Empirical Lane Quantiles vs LightGBM Continuous Coverage

In DataCo, transit days and scheduled days are discrete integers. As a result, transit residuals $y$ are coarse discrete steps:
- $y \in \{-2, -1, 0, 1, 2, 3, 4\}$

The table below contrasts the test-set coverage ($\text{fraction of actuals} \le \hat{q}$) between the shipped empirical lane quantiles and the LightGBM continuous model:

| Quantile | Nominal Target | Shipped Empirical Quantiles Coverage | LightGBM Monotonic Corrected Coverage | LightGBM Raw Coverage |
|:---|:---:|:---:|:---:|:---:|
| **P10** | 10.0% | **32.85%** | 9.66% | 10.69% |
| **P50** | 50.0% | **66.40%** | 51.77% | 53.43% |
| **P85** | 85.0% | **100.00%** | 83.66% | 80.96% |

**Why Empirical Coverage Exceeds Nominal Percentiles:**
The shipped empirical lane quantiles are discrete mode-level integer offsets:
- `AIR`: $P_{10} = 0, P_{50} = 1, P_{85} = 1$
- `RAIL`: $P_{10} = 0, P_{50} = 2, P_{85} = 4$
- `SEA`: $P_{10} = -2, P_{50} = 0, P_{85} = 2$

Because cumulative probability distributions for discrete integers jump at integer boundaries, taking discrete integer cutoffs ensures that 100% of sea, air, and rail test shipments fall at or below their respective $P_{85}$ residual. For example, in SEA mode ($N = 5,131$ in test holdout), the maximum observed delay residual is $+2$ days; hence choosing $P_{85} = 2$ covers 100.0% of historical cases. In contrast, LightGBM fits continuous real-valued approximations (e.g., $P_{85} \approx 1.87$), slicing through the discrete point mass at $+2$ and yielding 83.66% coverage.

### 1.3 Serving Code Verification & Negative Result Archiving

To fulfill Decision Option A without regression risk:
1. `src/nexafreight/ml/eta_model.py` contains `LANE_QUANTILES_TABLE` mapping modes to calibrated discrete integer quantiles.
2. `EtaQuantileModel.load()` loads metadata and validates schemas without deserializing `model.joblib`.
3. Dedicated proof test `backend/tests/unit/test_eta_serves_lane_quantiles.py` asserts:
   - `POST /api/predict/eta` serves exact empirical residuals (`SEA`: $[-2, 0, 2]$, `AIR`: $[0, 1, 1]$) with provenance `DERIVED`.
   - `GET /api/shipments/{id}/predict` serves SLA risk and median ETA with provenance `DERIVED`.
   - Both endpoints execute under a test guard that raises an `AssertionError` if any attempt is made to invoke `joblib.load()` on `eta_quantile/model.joblib`.

---

## 2. Delay Classifier Audit: Leakage, Ablation, and Synthetic Label Root Cause (2C)

### 2.1 Headline Finding: Synthetic Labelling Rule Recovery

The delay classifier achieves **0.7273 test ROC-AUC** across the 14 pre-ship features. However, an analysis of single-feature predictive power reveals that:
- A naive baseline grouped on `shipping_mode` alone attains **0.7095 test ROC-AUC** (accounting for **92.2%** of all excess AUC above random 0.50).
- `scheduled_shipping_days` alone achieves **0.7289 ROC-AUC**.
- The classifier does not uncover hidden logistical risk dynamics. Instead, it recovers the deterministic synthetic rule used by the DataCo dataset creators to assign shipping days and late delivery flags.

### 2.2 Cross-Tabulation: Late Delivery Rate by Shipping Mode

In DataCo, `Late_delivery_risk` is defined as $\mathbb{I}(\text{Days for shipping (real)} > \text{Days for shipment (scheduled)})$. The table below summarizes sample counts $N$ and late delivery rates across chronological splits:

| Split | Metric | AIR | RAIL | SEA | Overall Split |
|:---|:---|:---:|:---:|:---:|:---:|
| **Train** ($N = 46,711$) | Count ($N$) | 9,723 | 9,076 | 27,912 | 46,711 |
| | Late Rate | **82.26%** (7,998) | **76.83%** (6,973) | **38.24%** (10,674) | **54.90%** (25,645) |
| **Validation** ($N = 10,461$) | Count ($N$) | 2,151 | 2,029 | 6,281 | 10,461 |
| | Late Rate | **82.43%** (1,773) | **76.05%** (1,543) | **37.65%** (2,365) | **54.31%** (5,681) |
| **Test** ($N = 8,580$) | Count ($N$) | 1,776 | 1,673 | 5,131 | 8,580 |
| | Late Rate | **83.28%** (1,479) | **76.93%** (1,287) | **38.12%** (1,956) | **55.03%** (4,722) |

**Observations:**
- The late delivery rate is virtually invariant across the chronological time axis: AIR is always ~82.3–83.3%, RAIL is always ~76.1–76.9%, and SEA is always ~37.7–38.2%.
- Because scheduled shipping days were statically set (Standard Class = 4 days, Second Class = 2 days, First Class = 1 day, Same Day = 0 days), any transport mode with real shipping days averaging ~2-4 days experiences massive synthetic late rates for expedited modes (AIR/RAIL) and low late rates for standard modes (SEA).

### 2.3 Single-Feature ROC-AUC for All 14 Features (Ranked)

Each of the 14 pre-ship features was evaluated individually using univariate logistic / isotonic predictions against test holdout labels:

| Rank | Feature Name | Feature Type | Univariate Test ROC-AUC | Learnable Signal Assessment |
|:---:|:---|:---:|:---:|:---|
| 1 | `scheduled_shipping_days` | Numeric | **0.7289** | Synthetic mode-schedule mapping |
| 2 | `shipping_mode` | Categorical | **0.7095** | High-cardinality mode mapping |
| 3 | `order_profit` | Numeric | **0.5045** | Pure noise ($0.50 \pm 0.01$) |
| 4 | `shipping_cost` | Numeric | **0.5042** | Pure noise ($0.50 \pm 0.01$) |
| 5 | `sla_month` | Numeric | **0.5038** | Pure noise ($0.50 \pm 0.01$) |
| 6 | `revenue` | Numeric | **0.5034** | Pure noise ($0.50 \pm 0.01$) |
| 7 | `order_country` | Categorical | **0.5024** | Pure noise ($0.50 \pm 0.01$) |
| 8 | `sla_quarter` | Numeric | **0.5007** | Pure noise ($0.50 \pm 0.01$) |
| 9 | `total_distance_km` | Numeric | **0.5000** | Pure noise (zero correlation with synthetic late flag) |
| 10 | `leg_count` | Numeric | **0.5000** | Pure noise (zero correlation with synthetic late flag) |
| 11 | `cargo_class` | Categorical | **0.4990** | Pure noise ($0.50 \pm 0.01$) |
| 12 | `sla_weekday` | Numeric | **0.4988** | Pure noise ($0.50 \pm 0.01$) |
| 13 | `product_price` | Numeric | **0.4946** | Pure noise ($0.50 \pm 0.01$) |
| 14 | `customer_country` | Categorical | **0.4944** | Pure noise ($0.50 \pm 0.01$) |

**Conclusion:** 12 out of 14 features have an ROC-AUC within $[0.494, 0.505]$, confirming that none of commercial terms, route distance, geography, or calendar timing possess meaningful predictive signal for DataCo delay labels.

### 2.4 Feature Ablation: Removal of Mode and Schedule

To verify that the model's apparent skill relies exclusively on mode and schedule features, an ablation experiment was conducted retraining LightGBM without `shipping_mode` and `scheduled_shipping_days`:

- **Full Model (14 features):** Test ROC-AUC = **0.7273**
- **Ablated Model (12 features without mode and scheduled days):** Test ROC-AUC = **0.5007**
- **AUC Collapse:** $\Delta \text{AUC} = \mathbf{-0.2266}$

Without mode information, the model's performance drops to random chance (0.5007), proving that no other features carry independent predictive signal.

### 2.5 Bootstrap 95% Confidence Interval on Delta AUC

To determine whether the full 14-feature LightGBM model offers a statistically significant lift over a simple grouped lookup on `shipping_mode`:
- Grouped `shipping_mode` baseline: Test ROC-AUC = **0.7095**
- Full 14-feature LightGBM model: Test ROC-AUC = **0.7273**
- 1,000 bootstrap iterations over test holdout orders ($N = 8,580$):
  - **Mean Lift ($\Delta \text{AUC}$):** **+0.0178**
  - **95% Bootstrap Confidence Interval:** **`[0.0105, 0.0254]`**

The small positive lift (+0.0178 AUC) indicates modest non-linear refinement over the mode marginal, but does not alter the conclusion that the model is overwhelmingly fitting mode-specific constants.

### 2.6 Codebase Verification: `total_distance_km` and `leg_count` Non-Leakage

Concerns were evaluated regarding whether `total_distance_km` or `leg_count` might accidentally ingest delivery outcomes:
- **Serving Path (`backend/src/nexafreight/api/routes/shipments.py:529-531`):**
  ```python
  live_legs = [l for l in shipment.legs if str(l.status) != _LegStatus.REPLACED]
  total_km = sum(l.distance_km or 0.0 for l in live_legs)
  leg_count = max(1, len(live_legs))
  ```
  `live_legs` is filtered strictly on planned routing geometry. `distance_km` is the spatial haversine / maritime corridor distance between origin and destination coordinates.
- **Training Pipeline (`backend/scripts/10_build_features.py`):**
  `total_distance_km` is computed via coordinate geography; `leg_count` is the count of scheduled transit legs.
- **Auditing Result:** Neither feature accesses `days_for_shipping_real`, `delivery_status`, `actual_arrival`, or AIS slip telemetry. Both are 100% pre-departure spatial properties.

### 2.7 Permutation Test: Pipeline Sanity Check

In previous drafts, label permutation was characterized as "proving zero target leakage". That description was incorrect: **label permutation cannot detect feature leakage** (e.g. if a feature contains future information, shuffling the training target will still break the association between that feature and the scrambled target).

The label permutation test is retained here strictly as a **pipeline sanity check**:
- Target labels were randomly permuted during training: $\tilde{y}_{\text{train}} \sim \text{Permute}(y_{\text{train}})$.
- Validation ROC-AUC dropped from 0.7238 to 0.5216; test ROC-AUC dropped from 0.7273 to 0.5079.
- **Purpose:** Confirms that the training and evaluation pipeline correctly measures statistical association rather than artifactual data alignment or software bugs.

### 2.8 LightGBM Early Stopping (`best_iteration: 3`)

Previous internal discussions attributed `best_iteration: 3` to "Optuna trial counts". This is technically inaccurate:
- Hyperparameter tuning selected LightGBM tree induction with early stopping (`early_stopping_rounds: 10`).
- Tree induction halted at iteration 3 (`best_iteration: 3`) because LightGBM early stopping observed that validation log-loss ceased improving after 3 trees.
- With only `shipping_mode` and `scheduled_shipping_days` carrying signal, a tree depth of 3 completely partitions the 3 modes and 4 scheduled day tiers. Additional trees simply overfit validation noise.

---

## 3. Demand Forecast Verification & Synthetic Volume Caveat (2D)

### 3.1 StatsForecast AutoETS Performance Summary

- **Architecture:** `StatsForecast AutoETS` (Additive Error, Trend, Seasonality with season length 4 weeks).
- **Lanes:** 79 out of 675 lanes met the minimum threshold of 26 historical weekly observations.
- **Holdout Evaluation:** 13-week out-of-time chronological horizon.
- **WAPE:** **32.16%** vs Seasonal Naive 44.02% (**+26.94% lift**).
- **MASE:** Median **0.7285** (63 of 79 lanes with $\text{MASE} \le 1.0$).
- **Clean Naming:** 100% compliant across backend code, API schemas, frontend components, and documentation (all legacy Prophet naming eliminated).

### 3.2 Synthetic DataCo Order Volume Limitation

While AutoETS produces well-calibrated time series forecasts, users and operators must be advised that **DataCo order volumes were generated synthetically**. Seasonal patterns reflect the synthetic periodicity injected by the dataset generators rather than macroeconomic trade fluctuations.

---

## 4. Summary of Evidentiary Artifacts

All raw empirical evaluations, ablation runs, and test outputs are persisted in the repository:
- `backend/evidence/pr2/delay_ablation_results.json`: Cross-tabulations, single-feature AUCs, ablation AUC (0.5007), and bootstrap 95% CI.
- `backend/evidence/pr2/pinball_recomputation_results.json`: Raw and corrected pinball losses, baseline losses, and discrete vs continuous coverage rates.
- `backend/tests/unit/test_eta_serves_lane_quantiles.py`: Proof test asserting that serving routes deliver lane quantiles without deserializing `model.joblib`.
