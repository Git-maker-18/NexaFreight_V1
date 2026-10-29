# NexaFreight Operational Runbook

This runbook documents operational procedures for deploying, monitoring, rolling back, and maintaining the NexaFreight Control Tower system.

---

## 1. Production Deployment

### Backend Deployment (Render)
1. Ensure all CI gates pass on the `release` branch.
2. In the Render Dashboard, navigate to `nexafreight-backend` -> **Manual Deploy** -> **Deploy latest commit**.
3. Stream deployment logs to observe the non-root entrypoint sequence:
   - Pre-flight migration lock acquired (`pg_try_advisory_lock(42891)`).
   - Alembic runs `alembic upgrade head`.
   - Uvicorn initializes non-root workers.
4. Verify deployment health:
   ```bash
   curl -i https://nexafreight-backend.onrender.com/readyz
   # Expected: HTTP 200 {"status":"ready"}
   ```

### Frontend Deployment (Vercel)
1. Connect the GitHub repository to Vercel with Root Directory set to `frontend`.
2. Configure Environment Variables:
   - `BACKEND_URL`: `https://nexafreight-backend.onrender.com` (Server-only variable; DO NOT set as `NEXT_PUBLIC_*`).
   - `NEXT_PUBLIC_UMAMI_WEBSITE_ID`: Optional analytics tracking ID.
3. Deploy and verify that same-origin requests resolve cleanly:
   ```bash
   curl -i https://your-frontend.vercel.app/api/nexa/readyz
   # Expected: HTTP 200 {"status":"ready"}
   ```

---

## 2. Emergency Rollback Procedures

### Backend Rollback
1. In Render Dashboard, click **Deploys**.
2. Locate the last known good deploy and click **Rollback to this deploy**.
3. Render immediately restores the previous container image SHA without rebuilding.

### Database State Restoration (Neon)
1. If an erroneous migration or data corruption occurs, navigate to the Neon Console.
2. Locate the golden branch created prior to rollout (e.g. `pre-hardening-20261029`).
3. Restore from the point-in-time snapshot or promote the branch to primary:
   ```bash
   neon branches create --from pre-hardening-20261029 --name rollback-primary
   ```
4. Update `DATABASE_URL` in Render environment variables with the restored branch connection string.

---

## 3. Secret Rotation Procedures

### JWT Secret (`JWT_SECRET`)
1. Generate a cryptographically secure 64-character random string:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. In Render Dashboard -> **Environment**, update `JWT_SECRET`.
3. Save changes; Render automatically restarts backend workers.
4. *Effect*: Existing user JWT sessions will expire and require re-authentication.

### Nightly Sync Secret (`NIGHTLY_SECRET`)
1. Generate a new secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update `NIGHTLY_SECRET` in Render Environment Variables.
3. Update `NEXA_NIGHTLY_SECRET` in GitHub Repository Secrets (`Settings` -> `Secrets and variables` -> `Actions`).
4. Trigger workflow test: Navigate to GitHub Actions -> **Nightly ingestion** -> **Run workflow**.

---

## 4. Verification & Diagnostics

### Liveness vs. Readiness Probes
- `/healthz`: Liveness probe — verifies FastAPI process is responding. Does not query database.
- `/readyz`: Readiness probe — performs an active SQL ping (`SELECT 1`) with a 2-second timeout. Returns HTTP 503 if database connectivity fails.

### SSE Stream Diagnostics
To verify that SSE streaming requires short-lived tickets:
```bash
# 1. Unauthenticated request must return 401
curl -i https://nexafreight-backend.onrender.com/api/map/positions/stream
# Expected: HTTP 401 Unauthorized

# 2. Query param ?token= must return 401 (deprecated)
curl -i "https://nexafreight-backend.onrender.com/api/map/positions/stream?token=invalid"
# Expected: HTTP 401 Unauthorized
```
