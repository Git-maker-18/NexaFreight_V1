# NexaFreight Known Issues & Technical Limitations

This document catalogs known issues, verified performance boundaries, and deliberate design trade-offs across the NexaFreight Control Tower system.

---

## 1. Algorithmic Boundaries (ALG-01)

### Pareto-Dominated Itineraries (5 Expected xfail Tests)
- **Description**: The multimodal route planner evaluates itineraries across three competing dimensions: operational cost (USD), transit duration (hours), and CO2 emissions (kg). On complex multi-hop transshipment graphs, branch-and-bound heuristic pruning occasionally retains itineraries that are weakly dominated (i.e. tied in one dimension, inferior in another).
- **Impact**: 5 tests in `backend/tests/unit/test_planner_pareto.py` are explicitly marked with `@pytest.mark.xfail(strict=True)` to track these edge cases.
- **Root Cause**: Heuristic beam search prioritizes latency over exhaustive Pareto frontier verification on large international transport graphs.
- **Remediation Plan**: Transition to an exact bicriteria Label Setting algorithm for corridor optimization in v1.1.0.

---

## 2. Machine Learning Boundaries

### ML-01: Delay Classifier Ceiling (Synthetic Label Recovery)
- **Description**: The delay risk classifier achieves a test ROC-AUC of **0.7273**. However, single-feature evaluation proves `scheduled_shipping_days` alone achieves **0.7289** AUC, and `shipping_mode` achieves **0.7095** AUC. Removing both collapses ROC-AUC to **0.5007** (near-random guessing).
- **Operational Reality**: In the DataCo Smart Supply Chain dataset, "shipping mode" is a direct proxy for commercial service level (`Standard Class` → SEA, `Second Class` → RAIL, `First Class / Same Day` → AIR). The labels were synthetically assigned based on service-class rules. The classifier predominantly recovers this synthetic rule rather than predicting dynamic real-world logistics bottlenecks.
- **Safeguard**: Documented in `backend/eval/LEAKAGE_AND_QUANTILE_AUDIT.md` and README. The model is surfaced with provenance `DERIVED`.

### ML-02: ETA Quantile Regression Negative Result
- **Description**: A multi-quantile LightGBM model trained to estimate P10, P50, and P85 residual delay failed to beat empirical historical mode baselines, showing negative pinball loss lift (-0.23% to -1.94%).
- **Remediation**: The model artifact (`model.joblib`) was decommissioned from serving paths. Both `/api/predict/eta` and `/api/shipments/{id}/predict` serve directly from `LANE_QUANTILES_TABLE` with provenance `DERIVED`. The trained LightGBM artifacts are retained in `eval/` strictly as a documented benchmark.

---

## 3. Infrastructure & Deployment Boundaries

### INFRA-01: Free-Tier Backend Cold Starts
- **Description**: When deployed on Render free instances, the backend enters idle sleep after 15 minutes of inactivity. The first inbound request triggers an instance wake-up taking approximately 45–55 seconds.
- **Remediation**: 
  - Implemented `BackendColdStartBanner` in the frontend to detect stalled `/health` requests and notify the user with an animated indicator.
  - Implemented `/healthz` (liveness probe) and `/readyz` (readiness probe with 2.0s DB timeout).

### INFRA-02: Background Scheduler Concurrency
- **Description**: APScheduler in-process background triggers could conflict with scheduled GitHub Actions cron workflows if both execute identical sync tasks simultaneously.
- **Remediation**: Production instances disable in-process scheduler tasks via `ENABLE_BACKGROUND_SCHEDULER=false` and rely on authenticated HMAC endpoints (`/internal/nightly`) triggered by `.github/workflows/nightly.yml`.

---

## 4. External API Failure Fallbacks

| Upstream Provider | Role | Failure State | Fallback Behavior |
| :--- | :--- | :--- | :--- |
| **AISStream.io** | Live vessel positions | WebSocket disconnect / API key exhaustion | Replays historical AIS parquet tracks (`REPLAYED`) or falls back to dead-reckoning (`SIMULATED`). |
| **OpenRouteService (ORS)** | High-precision road routing | 429 Quota Exceeded / 5xx error | Great-circle Haversine distance multiplied by road circuity factor (1.30). |
| **Open-Meteo / GDACS** | Severe weather & alerts | API timeout | Historical climatology risk zones and synthetic corridor alerts (`SIMULATED`). |
| **Gemini Flash / Ollama** | Natural language copilot | Quota exhaustion / server down | Rule-based deterministic response (`rules_fallback`) from verified database metrics. |
