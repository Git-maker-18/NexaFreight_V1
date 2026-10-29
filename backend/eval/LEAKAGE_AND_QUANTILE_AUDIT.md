# NexaFreight ML Audit: Delay Classifier Leakage & ETA Quantile Benchmark (Phase 2, PR 2)

**Audit Date:** 2026-10-29  
**Branch:** `fix/pr2-glec-co2-and-ml-resolution`  
**Review Target:** ML-02 (ETA Quantiles vs Service-Level Empirical Bands) and Delay Classifier (Single-Feature AUC, Joint Baseline Bootstrap CI, Feature Ablation, and Pipeline Sanity).

---

## Executive Summary

1. **CO₂ Factor Unification (ML-03 / 2A):**
   Authoritative GLEC Framework v3.2 multimodal emission factors (`SEA: 8.0`, `ROAD: 62.0`, `RAIL: 28.0`, `AIR: 602.0` g/t-km) are established as the single source of truth in `nexafreight.core.constants`. All divergent runtime constants (e.g., 12.0, 6.5, road 62.0 copied to sea) have been removed. Alembic data migration `f7a8b9c0d1e2` backfills existing legs and parameter tables with comprehensive migration tests passing (8/8).

2. **ETA Quantiles Resolution (ML-02 / 2B — Option A):**
   LightGBM quantile regression yielded negative lift against the grouped empirical baseline across all three quantiles (P10: -0.23%, P50: -0.36%, P85: -1.94%). The P10/P50/P85 transit bounds are formally served as **service-level empirical bands from synthetic DataCo delays** with provenance **`DERIVED`**. Serving code in `/api/predict/eta` and `/api/shipments/{id}/predict` serves directly from `LANE_QUANTILES_TABLE` without deserializing `model.joblib`, verified by automated tests.

3. **Delay Classifier Dynamics & Synthetic Labelling (2C):**
   - **Headline Finding:** The full 14-feature gradient boosted tree model adds **zero incremental predictive value** over `scheduled_shipping_days` alone (0.7273 test ROC-AUC vs 0.7289 single-feature ROC-AUC; mean difference **-0.0016**, 95% bootstrap CI `[-0.0075, +0.0044]`). Likewise, it adds zero incremental lift over a joint `(shipping_mode x scheduled_shipping_days)` grouped lookup (0.7273 vs 0.7289). The classifier predominantly recovers DataCo's deterministic synthetic labelling rule rather than learning real-world delay dynamics. The 0.727 test ROC-AUC does not indicate real-world operational delay predictability.
   - **Mode as Service Proxy:** DataCo does not distinguish true physical transport modes (SEA, RAIL, AIR, ROAD). In `01_ingest_dataco.py:141-150`, shipping classes are mapped as Standard $\to$ SEA, Second $\to$ RAIL, First/Same Day $\to$ AIR. Scheduled days are deterministic functions of these service tiers.
   - **Constant Route Properties in Training:** `total_distance_km` and `leg_count` have standard deviation **0.0** and unique count **1** (all 46,711 training rows have value 0.0); they are **not informative (constant in training)**.
   - **Ablation Collapse:** Ablating `shipping_mode` and `scheduled_shipping_days` causes test ROC-AUC to collapse from **0.7273 to 0.5007** (random guessing). The remaining 12 pre-ship features contain zero independent predictive signal.
   - **LightGBM Early Stopping:** Tree induction terminated at iteration 3 (`best_iteration: 3`) because LightGBM early stopping detected that validation loss ceased improving once the mode-to-late-rate mapping was captured.
   - **Permutation Test Clarification:** The label permutation experiment is documented strictly as a **pipeline sanity check** (confirming that gradient boosting converges to random guessing ~0.50 AUC under independent random labels). It cannot detect feature leakage.

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

**Explanation of Pinball Discrepancy (0.5060 and 0.2598):**
The figures 0.5060 and 0.2598 originated from an earlier training run recorded in `backend/eval/report.md` (model artifact SHA `b3954a466dbd8bc2`). That earlier run was subsequently superseded by the committed champion model (`72d70b1ab131c12a`), which achieved raw test losses of 0.5053 (P50) and 0.2568 (P85), and monotonic corrected losses of 0.5054 (P50) and 0.2562 (P85) as recorded in `models/eta_quantile/metadata.json`. The numbers 0.5060 and 0.2598 are therefore documented as **origin identified: superseded earlier training run**.

### 1.2 Mathematical Quantile Validity Condition

For discrete integer delay distributions, an empirical quantile $q$ at nominal level $\alpha$ is mathematically valid if and only if:
$$P(y < q) \le \alpha \le P(y \le q)$$

Below are the empirical evaluation metrics computed across all training and test observations in `evidence/pr2/quantile_validity_results.json`:

| Split | Mode | Quantile | Offset $q$ | Target $\alpha$ | $P(y < q)$ | $P(y \le q)$ | Valid? ($P(y < q) \le \alpha \le P(y \le q)$) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Train** ($N = 44,179$) | **AIR** ($N = 7,191$) | P10 | +1.0 | 0.10 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.10 \le 1.0$) |
| | | P50 | +1.0 | 0.50 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.50 \le 1.0$) |
| | | P85 | +1.0 | 0.85 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.85 \le 1.0$) |
| | **RAIL** ($N = 9,076$) | P10 | +0.0 | 0.10 | 0.0000 | 0.2005 | **True** ($0.0 \le 0.10 \le 0.2005$) |
| | | P50 | +2.0 | 0.50 | 0.3996 | 0.5995 | **True** ($0.3996 \le 0.50 \le 0.5995$) |
| | | P85 | +4.0 | 0.85 | 0.7987 | 1.0000 | **True** ($0.7987 \le 0.85 \le 1.0$) |
| | **SEA** ($N = 27,912$) | P10 | -2.0 | 0.10 | 0.0000 | 0.2005 | **True** ($0.0 \le 0.10 \le 0.2005$) |
| | | P50 | +0.0 | 0.50 | 0.4011 | 0.6005 | **True** ($0.4011 \le 0.50 \le 0.6005$) |
| | | P85 | +2.0 | 0.85 | 0.7987 | 1.0000 | **True** ($0.7987 \le 0.85 \le 1.0$) |
| **Test** ($N = 8,109$) | **AIR** ($N = 1,305$) | P10 | +1.0 | 0.10 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.10 \le 1.0$) |
| | | P50 | +1.0 | 0.50 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.50 \le 1.0$) |
| | | P85 | +1.0 | 0.85 | 0.0000 | 1.0000 | **True** ($0.0 \le 0.85 \le 1.0$) |
| | **RAIL** ($N = 1,673$) | P10 | +0.0 | 0.10 | 0.0000 | 0.1973 | **True** ($0.0 \le 0.10 \le 0.1973$) |
| | | P50 | +2.0 | 0.50 | 0.3945 | 0.5971 | **True** ($0.3945 \le 0.50 \le 0.5971$) |
| | | P85 | +4.0 | 0.85 | 0.7992 | 1.0000 | **True** ($0.7992 \le 0.85 \le 1.0$) |
| | **SEA** ($N = 5,131$) | P10 | -2.0 | 0.10 | 0.0000 | 0.2005 | **True** ($0.0 \le 0.10 \le 0.2005$) |
| | | P50 | +0.0 | 0.50 | 0.4003 | 0.6003 | **True** ($0.4003 \le 0.50 \le 0.6003$) |
| | | P85 | +2.0 | 0.85 | 0.7987 | 1.0000 | **True** ($0.7987 \le 0.85 \le 1.0$) |

**Derivation Script and Operational Assumptions:**
- The empirical lane quantiles are derived directly from DataCo training records via `backend/scripts/derive_lane_quantiles.py` and regenerated/verified by `backend/tests/unit/test_eta_serves_lane_quantiles.py::test_lane_quantiles_table_matches_data_derivation`.
- `ROAD` and `DEFAULT` rows in `LANE_QUANTILES_TABLE` are **heuristic operational assumptions**: exactly 0 rows exist for `ROAD` in DataCo data.

### 1.3 Serving Code Verification & Negative Result Archiving

To fulfill Decision Option A without regression risk:
1. `src/nexafreight/ml/eta_model.py` contains `LANE_QUANTILES_TABLE` mapping modes to empirical quantile offsets.
2. `EtaQuantileModel.load()` loads metadata and validates schemas without deserializing `model.joblib`.
3. Dedicated proof test `backend/tests/unit/test_eta_serves_lane_quantiles.py` asserts:
   - `POST /api/predict/eta` serves exact empirical residuals (`SEA`: $[-2, 0, 2]$, `AIR`: $[1, 1, 1]$, `RAIL`: $[0, 2, 4]$) with provenance `DERIVED`.
   - `GET /api/shipments/{id}/predict` serves SLA risk and median ETA with provenance `DERIVED`.
   - Both endpoints execute under a test guard asserting that `joblib.load()` is never called on `eta_quantile/model.joblib`.

---

## 2. Delay Classifier Audit: Leakage, Ablation, and Synthetic Label Root Cause (2C)

### 2.1 Headline Finding: Model Adds Zero Incremental Value Over Scheduled Days

The delay classifier achieves **0.7273 test ROC-AUC** across the 14 pre-ship features. However, an analysis of single-feature predictive power reveals that:
- `scheduled_shipping_days` alone achieves **0.7289 test ROC-AUC**.
- The full 14-feature LightGBM model achieves **0.7273 test ROC-AUC**.
- A joint baseline grouping on `(shipping_mode x scheduled_shipping_days)` achieves **0.7289 test ROC-AUC**.
- **The full model adds zero incremental predictive value over scheduled shipping days alone or the joint baseline.** The mean difference in test AUC is **-0.0016** with a 95% bootstrap confidence interval of **`[-0.0075, +0.0044]`** (spanning zero).
- The classifier does not uncover real-world logistical risk dynamics. Instead, it recovers the deterministic synthetic rule used by the DataCo dataset creators.

### 2.2 Mode as Proxy for DataCo Service Class

DataCo records do not represent physical freight modes (containerships, freight rail, cargo aircraft). In `backend/scripts/01_ingest_dataco.py:141-150`, shipping classes are mapped as follows:

```python
def map_shipping_mode(mode_str: str) -> str:
    """Map DataCo Shipping Mode to domain TransportMode (SEA, RAIL, AIR, ROAD)."""
    m = str(mode_str or "").strip().lower()
    if "standard" in m:
        return "SEA"
    if "second" in m:
        return "RAIL"
    if "first" in m or "same" in m:
        return "AIR"
    return "SEA"
```

In DataCo, `Days for shipment (scheduled)` is assigned deterministically by shipping class:
- **Standard Class** (mapped to SEA): scheduled days = 4 ($N = 27,912$ in train)
- **Second Class** (mapped to RAIL): scheduled days = 2 ($N = 9,076$ in train)
- **First Class / Same Day** (mapped to AIR): scheduled days = 1 or 0 ($N = 9,723$ in train)
- **ROAD**: 0 rows exist in the dataset; parameters are heuristic assumptions.

### 2.3 Cross-Tabulation: Late Delivery Rate by Shipping Mode

In DataCo, `Late_delivery_risk` is defined synthetically as $\mathbb{I}(\text{Days for shipping (real)} > \text{Days for shipment (scheduled)})$. The table below summarizes sample counts $N$ and late delivery rates across chronological splits:

| Split | Metric | AIR | RAIL | SEA | Overall Split |
|:---|:---|:---:|:---:|:---:|:---:|
| **Train** ($N = 46,711$) | Count ($N$) | 9,723 | 9,076 | 27,912 | 46,711 |
| | Late Rate | **82.26%** (7,998) | **76.83%** (6,973) | **38.24%** (10,674) | **54.90%** (25,645) |
| **Validation** ($N = 10,461$) | Count ($N$) | 2,151 | 2,029 | 6,281 | 10,461 |
| | Late Rate | **82.43%** (1,773) | **76.05%** (1,543) | **37.65%** (2,365) | **54.31%** (5,681) |
| **Test** ($N = 8,580$) | Count ($N$) | 1,776 | 1,673 | 5,131 | 8,580 |
| | Late Rate | **83.28%** (1,479) | **76.93%** (1,287) | **38.12%** (1,956) | **55.03%** (4,722) |

Because scheduled days were statically assigned to service classes, any transport mode where real shipping days average ~2-4 days produces high late rates for expedited classes (AIR/RAIL) and low late rates for standard class (SEA).

### 2.4 Single-Feature ROC-AUC for All 14 Features (Ranked)

Each of the 14 pre-ship features was evaluated individually using univariate predictions against test holdout labels:

| Rank | Feature Name | Feature Type | Univariate Test ROC-AUC | Learnable Signal Assessment |
|:---:|:---|:---:|:---:|:---|
| 1 | `scheduled_shipping_days` | Numeric | **0.7289** | Synthetic mode-schedule mapping (exceeds full model) |
| 2 | `shipping_mode` | Categorical | **0.7095** | Service-class proxy mapping |
| 3 | `order_profit` | Numeric | **0.5045** | Noise ($0.50 \pm 0.01$) |
| 4 | `shipping_cost` | Numeric | **0.5042** | Noise ($0.50 \pm 0.01$) |
| 5 | `sla_month` | Numeric | **0.5038** | Noise ($0.50 \pm 0.01$) |
| 6 | `revenue` | Numeric | **0.5034** | Noise ($0.50 \pm 0.01$) |
| 7 | `order_country` | Categorical | **0.5024** | Noise ($0.50 \pm 0.01$) |
| 8 | `sla_quarter` | Numeric | **0.5007** | Noise ($0.50 \pm 0.01$) |
| 9 | `total_distance_km` | Numeric | **0.5000** | Not informative (constant 0.0 in training, std = 0.0, unique = 1) |
| 10 | `leg_count` | Numeric | **0.5000** | Not informative (constant 0 in training, std = 0.0, unique = 1) |
| 11 | `cargo_class` | Categorical | **0.4990** | Noise ($0.50 \pm 0.01$) |
| 12 | `sla_weekday` | Numeric | **0.4988** | Noise ($0.50 \pm 0.01$) |
| 13 | `product_price` | Numeric | **0.4946** | Noise ($0.50 \pm 0.01$) |
| 14 | `customer_country` | Categorical | **0.4944** | Noise ($0.50 \pm 0.01$) |

**Conclusion:** 12 out of 14 features have an ROC-AUC within $[0.494, 0.505]$, confirming that none of commercial terms, geography, or calendar timing possess meaningful predictive signal for DataCo delay labels.

### 2.5 Distribution of Distance and Leg Features in Training

Audit of `data/processed/train.parquet` ($N = 46,711$) confirms:
- `total_distance_km`: standard deviation = **0.0**, unique values = **1** (all 46,711 rows are 0.0).
- `leg_count`: standard deviation = **0.0**, unique values = **1** (all 46,711 rows are 0).
- **Finding:** Neither feature carries signal during training because both features are **not informative (constant in training)** prior to route graph reconstruction.

### 2.6 Feature Ablation: Removal of Mode and Schedule

To verify that the model's apparent skill relies exclusively on mode and schedule features, LightGBM was retrained without `shipping_mode` and `scheduled_shipping_days`:
- **Full Model (14 features):** Test ROC-AUC = **0.7273**
- **Ablated Model (12 features without mode and scheduled days):** Test ROC-AUC = **0.5007**
- **AUC Collapse:** $\Delta \text{AUC} = \mathbf{-0.2266}$

Without mode and schedule, performance collapses to random chance (0.5007), proving that no other features carry independent predictive signal.

### 2.7 Bootstrap 95% Confidence Intervals on Incremental Lift

1,000 bootstrap iterations over test holdout orders ($N = 8,580$) evaluated incremental performance:
- **Full Model vs `scheduled_shipping_days` alone:**
  - Full model AUC: 0.7273
  - Scheduled days alone AUC: 0.7289
  - **Mean $\Delta \text{AUC}$:** **-0.0016** (95% CI: **`[-0.0075, +0.0044]`**)
  - *Result:* No statistically significant difference; the full model adds zero value.
- **Full Model vs Joint `(shipping_mode x scheduled_shipping_days)` Baseline:**
  - Full model AUC: 0.7273
  - Joint baseline AUC: 0.7289
  - **Mean $\Delta \text{AUC}$:** **-0.0016** (95% CI: **`[-0.0075, +0.0044]`**)
  - *Result:* Identical to scheduled days alone; the tree ensemble adds zero value over the joint table.
- **Full Model vs Grouped `shipping_mode` Alone:**
  - Mode baseline AUC: 0.7095
  - **Mean $\Delta \text{AUC}$:** **+0.0178** (95% CI: **`[0.0105, 0.0254]`**)
  - *Result:* The small lift reflects the non-linear relationship between scheduled days (0, 1, 2, 4) and late rates within modes.

### 2.8 Codebase Verification: `total_distance_km` and `leg_count` Non-Leakage

Concerns were evaluated regarding whether `total_distance_km` or `leg_count` might accidentally ingest delivery outcomes:
- **Serving Path (`backend/src/nexafreight/api/routes/shipments.py:529-531`):**
  ```python
  live_legs = [l for l in shipment.legs if str(l.status) != _LegStatus.REPLACED]
  total_km = sum(l.distance_km or 0.0 for l in live_legs)
  leg_count = max(1, len(live_legs))
  ```
  `live_legs` is filtered strictly on planned routing geometry. `distance_km` is the spatial haversine / maritime corridor distance between origin and destination coordinates.
- **Training Pipeline (`backend/scripts/10_build_features.py`):**
  Features represent pre-departure spatial properties. Neither feature accesses `days_for_shipping_real`, `delivery_status`, `actual_arrival`, or AIS slip telemetry.

### 2.9 Permutation Test: Pipeline Sanity Check

The label permutation test is documented strictly as a **pipeline sanity check**:
- Target labels were randomly permuted during training: $\tilde{y}_{\text{train}} \sim \text{Permute}(y_{\text{train}})$.
- Validation ROC-AUC dropped from 0.7238 to 0.5216; test ROC-AUC dropped from 0.7273 to 0.5079.
- **Purpose:** Confirms that the training and evaluation pipeline correctly measures statistical association rather than artifactual data alignment or software bugs. It cannot detect feature leakage.

### 2.10 LightGBM Early Stopping (`best_iteration: 3`)

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
- `evidence/pr2/delay_ablation_results.json` & `backend/evidence/pr2/delay_ablation_results.json`: Cross-tabulations, single-feature AUCs, ablation AUC (0.5007), and bootstrap 95% CI.
- `evidence/pr2/audit_revision_investigation.json`: Bootstrap comparison vs best single-feature and joint baseline, distance/leg distribution in train ($std=0.0$).
- `evidence/pr2/quantile_validity_results.json`: Mathematical quantile validity evaluation ($P(y < q) \le \alpha \le P(y \le q)$) across train and test.
- `evidence/pr2/pinball_recomputation_results.json`: Raw and corrected pinball losses, baseline losses, and discrete vs continuous coverage rates.
- `backend/scripts/derive_lane_quantiles.py`: Derivation script generating empirical lane quantiles from training data.
- `backend/tests/unit/test_eta_serves_lane_quantiles.py`: Proof tests asserting that serving routes deliver empirical lane quantiles without deserializing `model.joblib`, validating mathematical quantile bounds, and asserting identity against derived data.
