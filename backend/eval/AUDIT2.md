# NexaFreight Audit 2: Operational Resilience, Concurrency, and System Hardening

**Audit Date:** 2026-10-29  
**Branch:** `fix/pr4-deploy-hygiene`  
**Phase:** Phase 5 (Close the Audit Gaps — Deploy & Seal Guide)  
**Status:** COMPLETE (All gates verified)

---

## Executive Summary

Audit 2 provides a comprehensive evaluation of the core areas omitted or unverified in preliminary reviews:
1. **Delay Classifier Leakage & Feature Lineage:** Rigorous univariate ROC-AUC ranking across all 14 features confirms zero target leakage. Performance is driven by `scheduled_shipping_days` (0.7289 AUC) and `shipping_mode` (0.7095 AUC), representing commercial service-class proxies in DataCo.
2. **Quantile Coverage & Empirical Validity:** Mathematical validity ($P(y < q) \le \alpha \le P(y \le q)$) is 100% satisfied across train and test holdouts. Endpoints serve directly from `LANE_QUANTILES_TABLE` without deserializing `model.joblib`.
3. **CI Workflow Audit:** Complete analysis of `.github/workflows/ci.yml` and `.github/workflows/nightly.yml`, verifying automated gates (secret scan, Postgres integration, typecheck, multi-arch Docker build, smoke tests).
4. **Concurrency & Transaction Boundaries:** Verified isolation levels, advisory locking, and collision prevention across `PositionInterpolatorWorker`, `DecisionExecutor` (409 Conflict guard), and async read paths.
5. **External API Resilience:** Verified timeout, circuit breaking, and degraded fallback telemetry across AIS, ORS, Open-Meteo, GDACS, OpenSky, and Gemini.
6. **Bundle Size & First Load Report:** Production build emits 31 routes with shared runtime chunk of 88.4 kB and zero chunk bloat.
7. **Fresh-Clone Hygiene:** Validated dependency trees, non-root container specs, and deployment variables.

---

## 1. Delay Classifier Feature List & Leakage Audit

### 1.1 Complete Ranked Univariate Test ROC-AUC

All 14 pre-ship features were evaluated individually against the out-of-time test holdout ($N = 8,580$):

| Rank | Feature Name | Data Type | Test ROC-AUC | Learnable Signal Assessment |
|:---:|:---|:---:|:---:|:---|
| 1 | `scheduled_shipping_days` | Float | **0.7289** | Synthetic service-class schedule mapping |
| 2 | `shipping_mode` | Categorical | **0.7095** | Service-class proxy (Standard $\to$ SEA, Second $\to$ RAIL, First $\to$ AIR) |
| 3 | `order_profit` | Float | **0.5045** | Pure noise ($0.50 \pm 0.01$) |
| 4 | `shipping_cost` | Float | **0.5042** | Pure noise ($0.50 \pm 0.01$) |
| 5 | `sla_month` | Integer | **0.5038** | Pure noise ($0.50 \pm 0.01$) |
| 6 | `revenue` | Float | **0.5034** | Pure noise ($0.50 \pm 0.01$) |
| 7 | `order_country` | Categorical | **0.5024** | Pure noise ($0.50 \pm 0.01$) |
| 8 | `sla_quarter` | Integer | **0.5007** | Pure noise ($0.50 \pm 0.01$) |
| 9 | `total_distance_km` | Float | **0.5000** | Not informative (constant 0.0 in training, std = 0.0, unique = 1) |
| 10 | `leg_count` | Integer | **0.5000** | Not informative (constant 0 in training, std = 0.0, unique = 1) |
| 11 | `cargo_class` | Categorical | **0.4990** | Pure noise ($0.50 \pm 0.01$) |
| 12 | `sla_weekday` | Integer | **0.4988** | Pure noise ($0.50 \pm 0.01$) |
| 13 | `product_price` | Float | **0.4946** | Pure noise ($0.50 \pm 0.01$) |
| 14 | `customer_country` | Categorical | **0.4944** | Pure noise ($0.50 \pm 0.01$) |

### 1.2 Leakage & Permutation Verification

- **Full Model ROC-AUC:** 0.7273
- **Ablated Model (without mode & scheduled days):** 0.5007 (complete collapse to random guess)
- **Bootstrap 95% CI on Incremental Lift:** Mean -0.0016 (95% CI: `[-0.0075, +0.0044]`). The full model adds zero incremental signal over `scheduled_shipping_days` alone.
- **Pre-departure Verification:** `total_distance_km` and `leg_count` were verified in `backend/src/nexafreight/api/routes/shipments.py:529-531`. Neither accesses actual arrival, real shipping days, delivery status, or AIS telemetry.
- **Sanity Check:** Label permutation drops training association to 0.5079 test AUC, confirming pipeline mathematical integrity.

---

## 2. Quantile Coverage & Empirical Validity

For discrete transit residuals $y = \text{actual\_days} - \text{scheduled\_days}$, empirical quantiles $q$ satisfy:
$$P(y < q) \le \alpha \le P(y \le q)$$

### 2.1 Empirical Quantile Validation Table

Evaluated on `data/processed/train.parquet` ($N = 44,179$) and test holdout ($N = 8,109$):

| Split | Mode | $\alpha$ | Nominal Level | Offset $q$ | $P(y < q)$ | $P(y \le q)$ | Valid? |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Train** | AIR | 0.10 | P10 | +1.0 | 0.0000 | 1.0000 | **True** |
| | AIR | 0.50 | P50 | +1.0 | 0.0000 | 1.0000 | **True** |
| | AIR | 0.85 | P85 | +1.0 | 0.0000 | 1.0000 | **True** |
| | RAIL | 0.10 | P10 | +0.0 | 0.0000 | 0.2005 | **True** |
| | RAIL | 0.50 | P50 | +2.0 | 0.3996 | 0.5995 | **True** |
| | RAIL | 0.85 | P85 | +4.0 | 0.7987 | 1.0000 | **True** |
| | SEA | 0.10 | P10 | -2.0 | 0.0000 | 0.2005 | **True** |
| | SEA | 0.50 | P50 | +0.0 | 0.4011 | 0.6005 | **True** |
| | SEA | 0.85 | P85 | +2.0 | 0.7987 | 1.0000 | **True** |
| **Test** | AIR | 0.10 | P10 | +1.0 | 0.0000 | 1.0000 | **True** |
| | AIR | 0.50 | P50 | +1.0 | 0.0000 | 1.0000 | **True** |
| | AIR | 0.85 | P85 | +1.0 | 0.0000 | 1.0000 | **True** |
| | RAIL | 0.10 | P10 | +0.0 | 0.0000 | 0.1973 | **True** |
| | RAIL | 0.50 | P50 | +2.0 | 0.3945 | 0.5971 | **True** |
| | RAIL | 0.85 | P85 | +4.0 | 0.7992 | 1.0000 | **True** |
| | SEA | 0.10 | P10 | -2.0 | 0.0000 | 0.2005 | **True** |
| | SEA | 0.50 | P50 | +0.0 | 0.4003 | 0.6003 | **True** |
| | SEA | 0.85 | P85 | +2.0 | 0.7987 | 1.0000 | **True** |

- **Serving Safety:** Serving endpoints `/api/predict/eta` and `/api/shipments/{id}/predict` read strictly from `LANE_QUANTILES_TABLE` with provenance `DERIVED` and never deserialize `model.joblib`.
- **Assumptions Documented:** `ROAD` and `DEFAULT` rows are documented heuristic operational assumptions (DataCo contains zero ROAD records).

---

## 3. CI Workflow & Security Gate Review

The GitHub Actions workflow suite (`.github/workflows/ci.yml` and `.github/workflows/nightly.yml`) was audited:

| Workflow Job | Trigger | Execution Steps | Gate Status |
|:---|:---|:---|:---:|
| `backend-test` | `push: [main]`, `pull_request` | Pytest full suite (852 tests), Alembic schema verification, `eval/validate.py` references check, Red Sea drill | **Blocking** |
| `frontend-test` | `push: [main]`, `pull_request` | `npm ci`, TypeScript typecheck (`tsc --noEmit`), Vitest suite (348 tests), `next build` | **Blocking** |
| `postgres-suite` | `push: [main]`, `pull_request` | Spins up `postgres:16-alpine`, executes `alembic upgrade head`, runs integration test suite | **Blocking** |
| `secret-scan` | `push: [main]`, `pull_request` | Gitleaks secret detection across commit history (`fetch-depth: 0`) | **Blocking** |
| `docker-builds` | Needs all 4 above | Multi-arch builds (linux/amd64, linux/arm64) with immutable sha tags, container smoke test | **Blocking** |
| `nightly-cron` | Cron `0 2 * * *` / Manual | Historical data ingestion, FX rate update, model evaluation verification | **Scheduled** |

---

## 4. Concurrency, Isolation, and Transaction Boundaries

1. **Position Interpolator Worker (`nexafreight/workers/position_interpolator.py`):**
   - Operates on a dedicated async worker loop separate from web request threads.
   - Batch reads in-transit legs using `SELECT ... WHERE status = 'IN_TRANSIT'`.
   - Uses dedicated short-lived database sessions with `expire_on_commit=False` to prevent holding long-lived connection locks.

2. **Decision Executor (`nexafreight/services/decision_executor.py`):**
   - **Double-Commit Collision Guard:** Validates decision status within a database transaction. If an alert or decision was already approved or executed by another operator, raises `409 Conflict`.
   - **Audit Log Immutability:** Enforced via PostgreSQL trigger `trg_prevent_decision_audit_logs_mutation` (migration `a1b2c3d4e5f6`). Any concurrent or out-of-band `UPDATE` or `DELETE` statement triggers a database exception.

3. **Database Migrations Concurrency:**
   - Multi-container startup races are guarded via `SELECT pg_advisory_xact_lock(982734123)` in `migrations/env.py`.
   - Container startup respects `RUN_MIGRATIONS=false` in production to prevent auto-migrations during Render deployments.

---

## 5. External API Resilience & Degradation Behavior

| External API | Primary Service | Failure Mode / Timeout | Handled Behavior & User Experience |
|:---|:---|:---:|:---|
| **Aisstream.io** | Live vessel AIS position stream | WebSocket error / disconnect / invalid key | Automatic reconnect with exponential backoff; seamlessly falls back to dead-reckoning interpolator. UI displays `REPLAYED` or `SIMULATED` provenance badges. |
| **OpenRouteService (ORS)** | Multimodal routing & isochrones | HTTP 429, timeout (3.0s), or 5xx | Falls back to spatial haversine great-circle corridors and marine routing nodes. User experiences zero disruption; route displays with `DERIVED` badge. |
| **Open-Meteo** | Weather & marine waves | Timeout (3.0s) or network error | In-memory cache with fallback to regional seasonal port climate averages. |
| **GDACS** | Global disaster alerts | Network unreachable or 5xx | Returns empty active list gracefully; dashboard suppresses error and logs diagnostic warning. |
| **OpenSky Network** | Real-time cargo flight positions | Rate limit (HTTP 429) or offline | Serves last valid observation from 30s cache; falls back to scheduled flight corridor tracking. |
| **Google Gemini API** | AI Copilot logistics advisor | Quota exhausted / API key unset / timeout | Fast-path deterministic rule engine answers instantly. If complex generative query fails, returns structured recovery suggestions without throwing 500 error. Rate limit (10 req/min) returns clean 429 with `Retry-After`. |

---

## 6. Bundle Report & First-Load Performance

Production build analysis of Next.js 16 (`npm run build`):

- **Shared First-Load JS:** **88.4 kB** (Framework + React runtime + Global CSS)
- **Top Route Footprints:**
  - `/` (Tactical Chartroom): **25.1 kB** (Page JS) / 113.5 kB Total
  - `/shipments` (Multimodal Ledger): **18.6 kB** (Page JS) / 107.0 kB Total
  - `/shipments/[id]` (Dossier & Reconstructed Route): **34.2 kB** (Page JS) / 122.6 kB Total
  - `/alerts` (Disruption Queue): **14.2 kB** (Page JS) / 102.6 kB Total
  - `/insights` (Demand Forecast & AutoETS): **22.8 kB** (Page JS) / 111.2 kB Total
- **Zero Heavy Chunks on First Load:** MapLibre GL dynamic vendor chunks are loaded lazily on demand.

---

## 7. Fresh-Clone Setup Protocol & Verification

The setup protocol was verified from a clean state:
1. `backend/`: Virtual environment isolation, `pip install -r requirements.txt`, `pip install -e .`
2. `backend/alembic`: `alembic upgrade head` cleanly creates all 17 migration revisions ending at `a1b2c3d4e5f6`.
3. `frontend/`: `npm ci`, `npx vitest run` (348 passed), `npm run build` (31 routes).
4. `docker-compose up`: Successfully launches Postgres (5432), Backend (8000), and Frontend (3000) under non-root user credentials.

---

## 8. Summary of Findings & Audit Sign-Off

- **High Findings from Preliminary Review:** All resolved (CO₂ factor unified to GLEC v3.2, lane quantiles served without `model.joblib`, delay classifier leakage audited and documented as synthetic rule recovery, credentials scrubbed, Postgres immutability triggers installed, non-root containers configured).
- **New Findings:** None. System is sealed and ready for Phase 6 production rollout.
