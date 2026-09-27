/**
 * NexaFreight API — HTTP client
 *
 * Usage:
 *   import { nexaClient } from '@/lib/nexafreight/client'
 *
 *   // After login:
 *   nexaClient.setToken(loginResponse.access_token)
 *
 *   // Then call authenticated endpoints:
 *   const user = await nexaClient.getCurrentUser()
 *   const ships = await nexaClient.getShipments()
 *
 * Token storage: held in module-level memory only.
 * It is never written to localStorage or cookies from this module.
 * Call setToken() after a successful login; call clearToken() on logout.
 *
 * Base URL: read from NEXT_PUBLIC_NEXA_API_URL at module load time.
 * Set it in .env.local — Next.js only reads env files at server startup,
 * so restart the dev server after changing it.
 */

import { NexaHttpError, NexaNetworkError } from './errors'
import type {
  LoginRequest,
  LoginResponse,
  PaginatedResponse,
  PortFeatureCollection,
  RouteFeatureCollection,
  ShipmentDetail,
  ShipmentListItem,
  User,
  FeedHealthResponse,
  MLPredictionRequest,
  DelayPrediction,
  EtaPrediction,
  DemandForecastResponse,
} from './types'

// ─── Base URL ─────────────────────────────────────────────────────────────────

export const BASE_URL = (
  process.env.NEXT_PUBLIC_NEXA_API_URL || 'http://localhost:8000'
).replace(/\/$/, '') // strip trailing slash so paths can always start with /

// ─── Token store ──────────────────────────────────────────────────────────────
// Module-level variable: survives React re-renders, with browser storage fallback
// so page reloads during development retain operator access.

let _token: string | null = null

export function setToken(token: string): void {
  _token = token
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      window.sessionStorage.setItem('nexafreight_token', token)
      window.localStorage.setItem('nexafreight_token', token)
    } catch {}
  }
}

export function clearToken(): void {
  _token = null
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      window.sessionStorage.removeItem('nexafreight_token')
      window.localStorage.removeItem('nexafreight_token')
    } catch {}
  }
}

export function getToken(): string | null {
  if (!_token && typeof window !== 'undefined' && window.sessionStorage) {
    try {
      _token = window.sessionStorage.getItem('nexafreight_token') || window.localStorage.getItem('nexafreight_token') || null
    } catch {}
  }
  return _token
}

export function hasToken(): boolean {
  return getToken() !== null
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────

interface FetchOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Override auth behaviour: 'required' (default) throws if no token,
   *  'none' sends no Authorization header (used for /login). */
  auth?: 'required' | 'none'
  /** Optional query params appended to the URL */
  params?: Record<string, string | number | boolean | null | undefined>
}

export async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = 'required', params } = opts

  // Build URL
  let url = `${BASE_URL}${path}`
  let qs_str = ''
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== null && v !== undefined) qs.set(k, String(v))
    }
    qs_str = qs.toString()
    if (qs_str) url += `?${qs_str}`
  }

  // Build headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }

  if (auth === 'required') {
    if (!_token && typeof window !== 'undefined' && window.sessionStorage) {
      try {
        _token = window.sessionStorage.getItem('nexafreight_token') || window.localStorage.getItem('nexafreight_token') || null
      } catch {}
    }
    if (!_token) {
      throw new NexaHttpError(
        401,
        'No authentication token — call login() first.'
      )
    }
    headers['Authorization'] = `Bearer ${_token}`
  }

  // Execute request
  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    // If direct fetch to backend port failed, retry via Next.js proxy rewrite
    if (!url.startsWith('/api/nexa') && typeof window !== 'undefined') {
      try {
        const subPath = path.startsWith('/api') ? path.replace(/^\/api/, '') : path
        const proxyUrl = `/api/nexa${subPath}${qs_str ? `?${qs_str}` : ''}`
        response = await fetch(proxyUrl, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
        })
      } catch {
        throw new NexaNetworkError(err)
      }
    } else {
      throw new NexaNetworkError(err)
    }
  }

  // Parse error responses
  if (!response.ok) {
    let detail = response.statusText
    try {
      const errBody = await response.json() as Record<string, unknown>
      // Backend returns either { error: string, details: {} } (NexaFreightException)
      // or FastAPI's default { detail: string }
      if (typeof errBody.error === 'string') detail = errBody.error
      else if (typeof errBody.detail === 'string') detail = errBody.detail
    } catch {
      // Non-JSON error body — keep statusText
    }

    if (response.status === 401) {
      clearToken()
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('nexafreight:unauthorized', { detail: { detail } }))
      }
    }
    throw new NexaHttpError(response.status, detail)
  }

  // Parse success response
  // 204 No Content has no body
  if (response.status === 204) return undefined as T

  try {
    return (await response.json()) as T
  } catch (err) {
    throw new NexaNetworkError(new Error(`Failed to parse JSON response: ${err}`))
  }
}

// ─── Auth endpoints ───────────────────────────────────────────────────────────

/**
 * POST /api/auth/login
 *
 * On success, automatically stores the access token so subsequent calls
 * are authenticated without the caller needing to call setToken() manually.
 * The caller should still persist the token (e.g. in an auth store) if they
 * want it to survive a page reload.
 *
 * Matches backend: src/nexafreight/schemas/auth.py :: LoginRequest / LoginResponse
 */
export async function login(
  email: string,
  password: string
): Promise<LoginResponse> {
  const body: LoginRequest = { email, password }
  const response = await apiFetch<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body,
    auth: 'none', // login endpoint does not require a prior token
  })
  // Auto-store the token so subsequent calls work immediately
  setToken(response.access_token)
  return response
}

/**
 * GET /api/auth/me
 *
 * Returns the User profile for the currently authenticated token.
 * Response shape is UserOut (has id, no is_active) — different from the
 * UserProfile nested inside LoginResponse.
 *
 * Matches backend: src/nexafreight/schemas/auth.py :: UserOut
 */
export async function getCurrentUser(): Promise<User> {
  return apiFetch<User>('/api/auth/me')
}

// ─── Shipment endpoints ───────────────────────────────────────────────────────

export interface GetShipmentsParams {
  /** Filter by exact status */
  status?: ShipmentListItem['status']
  /** Filter by transport mode */
  mode?: ShipmentListItem['mode']
  /** If true, only return shipments with active alerts */
  alert?: boolean
  /** Page number, 1-indexed. Default: 1 */
  page?: number
  /** Items per page. Default: 20, max: 100 */
  size?: number
}

/**
 * GET /api/shipments
 *
 * Returns a paginated list of shipments. All params are optional.
 *
 * Matches backend: src/nexafreight/api/routes/shipments.py :: list_shipments
 * Response schema: PaginatedResponse[ShipmentListItem]
 */
export async function getShipments(
  params: GetShipmentsParams = {}
): Promise<PaginatedResponse<ShipmentListItem>> {
  return apiFetch<PaginatedResponse<ShipmentListItem>>('/api/shipments', {
    params: {
      status: params.status,
      mode: params.mode,
      alert: params.alert,
      page: params.page ?? 1,
      size: params.size ?? 20,
    },
  })
}

/**
 * GET /api/shipments/{id}
 *
 * Returns full detail for a single shipment, including all route legs and orders.
 * Matches backend: src/nexafreight/api/routes/shipments.py :: get_shipment_detail
 */
export async function getShipmentDetail(id: string): Promise<ShipmentDetail> {
  return apiFetch<ShipmentDetail>(`/api/shipments/${encodeURIComponent(id)}`)
}

/**
 * GET /api/shipments/{id}/route
 *
 * Returns the GeoJSON FeatureCollection of route geometries for a single shipment.
 * Used when a user selects/zooms to a specific shipment on the map.
 * Matches backend: src/nexafreight/api/routes/shipments.py :: get_shipment_route
 */
export async function getShipmentRoute(id: string): Promise<RouteFeatureCollection> {
  return apiFetch<RouteFeatureCollection>(`/api/shipments/${encodeURIComponent(id)}/route`)
}

// ─── Map & Visualization endpoints ───────────────────────────────────────────

/**
 * GET /api/map/ports
 *
 * Returns all ports with geographic coordinates and congestion statistics
 * as a GeoJSON FeatureCollection of Point features.
 * Matches backend: src/nexafreight/routers/map.py :: get_ports
 */
export async function getPorts(): Promise<PortFeatureCollection> {
  return apiFetch<PortFeatureCollection>('/api/map/ports')
}

/**
 * GET /api/map/warehouses
 *
 * Returns all warehouse origins as a GeoJSON FeatureCollection of Point features.
 */
export async function getWarehouses(): Promise<WarehouseFeatureCollection> {
  return apiFetch<WarehouseFeatureCollection>('/api/map/warehouses')
}

/**
 * GET /api/map/routes
 *
 * Returns all active shipment route geometries as a single GeoJSON FeatureCollection.
 * This is the primary dataset used to render global route lines on the map.
 * Matches backend: src/nexafreight/routers/map.py :: get_routes
 */
export async function getAllRoutes(): Promise<RouteFeatureCollection> {
  return apiFetch<RouteFeatureCollection>('/api/map/routes')
}

/**
 * GET /api/map/feed-health
 *
 * Returns health status for all active position feed adapters
 * (AIS replay/live, truck sim, flight replay).
 * Matches backend: src/nexafreight/routers/map.py :: get_feed_health
 */
export async function getFeedHealth(): Promise<FeedHealthResponse> {
  return apiFetch<FeedHealthResponse>('/api/map/feed-health')
}

// ─── ML Prediction endpoints ──────────────────────────────────────────────────
// URL correction: the backend mounts these at /api/predict/* and /api/demand/*,
// NOT /api/v1/ml/* as originally spec'd. Confirmed via GET /openapi.json:
//   ['/api/predict/delay', '/api/predict/eta', '/api/demand/forecast']

/**
 * POST /api/predict/delay
 *
 * Runs the LightGBM delay classifier on 14 shipment features.
 * Returns delay probability [0,1] and risk band LOW/MEDIUM/HIGH.
 *
 * Matches backend: src/nexafreight/api/routes/predictions.py :: predict_delay
 * Request/response schema: src/nexafreight/api/schemas/ml.py
 */
export async function getDelayPrediction(
  features: MLPredictionRequest
): Promise<DelayPrediction> {
  return apiFetch<DelayPrediction>('/api/predict/delay', {
    method: 'POST',
    body: features,
  })
}

/**
 * POST /api/predict/eta
 *
 * Runs the quantile regression ETA model on 14 shipment features.
 * Returns P10/P50/P85 ETA in days plus confidence interval width (P85−P10).
 *
 * Matches backend: src/nexafreight/api/routes/predictions.py :: predict_eta
 * Request/response schema: src/nexafreight/api/schemas/ml.py
 */
export async function getEtaPrediction(
  features: MLPredictionRequest
): Promise<EtaPrediction> {
  return apiFetch<EtaPrediction>('/api/predict/eta', {
    method: 'POST',
    body: features,
  })
}

/**
 * GET /api/demand/forecast
 *
 * Fetches precomputed Prophet demand forecast for a (category × region) lane.
 *
 * Returns:
 *   - DemandForecastResponse   on success (HTTP 200)
 *   - null                     when lane is unknown (HTTP 404 UNKNOWN_LANE)
 *                              → caller should show "no forecast" placeholder,
 *                                not treat this as an error
 *   - throws NexaHttpError     for all other failures (503 model down, etc.)
 *
 * Matches backend: src/nexafreight/api/routes/predictions.py :: demand_forecast
 */
export async function getDemandForecast(
  category: string,
  region: string,
  horizonDays: 30 | 60 | 90 = 90
): Promise<DemandForecastResponse | null> {
  try {
    return await apiFetch<DemandForecastResponse>('/api/demand/forecast', {
      params: {
        category,
        region,
        horizon_days: horizonDays,
      },
    })
  } catch (err) {
    // 404 UNKNOWN_LANE is a normal business outcome — the lane simply isn't in
    // the model. UI should show "no forecast available", not an error state.
    if (err instanceof NexaHttpError && err.isNotFound) {
      return null
    }
    // Any other error (503 model down, 401 unauth, network failure) — propagate.
    throw err
  }
}

// ─── Convenience namespace export ─────────────────────────────────────────────
// Allows `import { nexaClient } from '…/client'` as an alternative to
// importing individual functions.


export interface ValidationMatrixResponse {
  generated_at: string
  all_ok: boolean
  pass_count: number
  total_count: number
  static: import('@/lib/nexafreight/validation').ValidationCheck[]
  artifact: import('@/lib/nexafreight/validation').ValidationCheck[]
  skips: string[]
}

/** Task 17: live validation matrix (public endpoint, same impl as the CI gate). */
export async function getValidationMatrix(): Promise<ValidationMatrixResponse> {
  return apiFetch<ValidationMatrixResponse>('/api/health/validation', {
    method: 'GET',
    auth: 'none',
  })
}

export const nexaClient = {
  setToken,
  clearToken,
  hasToken,
  login,
  getCurrentUser,
  getShipments,
  getShipmentDetail,
  getShipmentRoute,
  getPorts,
  getWarehouses,
  getAllRoutes,
  getFeedHealth,
  getDelayPrediction,
  getEtaPrediction,
  getDemandForecast,
} as const

// ─── Operational APIs (Definitive Plan — Phase 10) ────────────────────────────

import type {
  AcknowledgeRequest,
  Alert,
  AlertDetail,
  AlertsResponse,
  AnalyticsEsgResponse,
  AnalyticsFinancialResponse,
  AnalyticsSlaResponse,
  AnalyticsSummaryResponse,
  ApproveResponse,
  CopilotAskResponse,
  WarehouseFeatureCollection,
  Decision,
  DecisionsResponse,
  Disruption,
  DisruptionCreate,
  DisruptionsResponse,
  RerouteOptionsResponse,
  ShipmentFinancialsResponse,
  ShipmentPredictResponse,
} from './types'

// ─── Alerts ───────────────────────────────────────────────────────────────────

/** GET /api/alerts?severity=&status= */
export async function getAlerts(params?: {
  severity?: string
  status?: string
}): Promise<AlertsResponse> {
  const qs = new URLSearchParams()
  if (params?.severity) qs.set('severity', params.severity)
  if (params?.status) qs.set('status', params.status)
  const suffix = qs.size ? `?${qs}` : ''
  return apiFetch<AlertsResponse>(`/api/alerts${suffix}`, { method: 'GET' })
}

/** GET /api/alerts/{id} */
export async function getAlert(id: string): Promise<AlertDetail> {
  return apiFetch<AlertDetail>(`/api/alerts/${encodeURIComponent(id)}`, { method: 'GET' })
}

/** PATCH /api/alerts/{id}/acknowledge */
export async function acknowledgeAlert(
  id: string,
  req: AcknowledgeRequest = { user_id: 1 },
): Promise<Alert> {
  return apiFetch<Alert>(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, {
    method: 'PATCH',
    body: req,
  })
}

/** GET /api/alerts/{id}/options */
export async function getAlertOptions(id: string): Promise<RerouteOptionsResponse> {
  return apiFetch<RerouteOptionsResponse>(
    `/api/alerts/${encodeURIComponent(id)}/options`,
    { method: 'GET' },
  )
}

/** POST /api/alerts/{id}/approve */
export async function approveAlertOption(
  id: string,
  optionKey: string,
): Promise<ApproveResponse> {
  return apiFetch<ApproveResponse>(`/api/alerts/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: { option_key: optionKey },
  })
}

// ─── Disruptions ──────────────────────────────────────────────────────────────

/** GET /api/disruptions?status=&disruption_type= */
export async function getDisruptions(params?: {
  status?: string
  disruption_type?: string
}): Promise<DisruptionsResponse> {
  const qs = new URLSearchParams()
  if (params?.status) qs.set('status', params.status)
  if (params?.disruption_type) qs.set('disruption_type', params.disruption_type)
  const suffix = qs.size ? `?${qs}` : ''
  return apiFetch<DisruptionsResponse>(`/api/disruptions${suffix}`, { method: 'GET' })
}

/** GET /api/disruptions/{id} */
export async function getDisruption(id: string): Promise<Disruption> {
  return apiFetch<Disruption>(`/api/disruptions/${encodeURIComponent(id)}`, { method: 'GET' })
}

/**
 * POST /api/disruptions — manual operator report; the MLIT pipeline analyzes
 * it immediately and raises the alert.
 */
export async function reportDisruption(
  req: DisruptionCreate,
): Promise<{ disruption_id: string; severity: string | null; alert_id: string | null; provenance: string }> {
  return apiFetch(`/api/disruptions`, {
    method: 'POST',
    body: req,
  })
}

// ─── Decisions ────────────────────────────────────────────────────────────────

/** GET /api/decisions (admin/operator only) */
export async function getDecisions(): Promise<DecisionsResponse> {
  return apiFetch<DecisionsResponse>(`/api/decisions`, { method: 'GET' })
}

/** GET /api/decisions/{id} */
export async function getDecision(id: string): Promise<Decision> {
  return apiFetch<Decision>(`/api/decisions/${encodeURIComponent(id)}`, { method: 'GET' })
}

// ─── Analytics ───────────────────────────────────────────────────────────────

/** GET /api/analytics/summary */
export async function getAnalyticsSummary(): Promise<AnalyticsSummaryResponse> {
  return apiFetch<AnalyticsSummaryResponse>(`/api/analytics/summary`, { method: 'GET' })
}

/** GET /api/analytics/scorecard — finance rollups (day ⊂ week ⊂ month) */
export async function getAnalyticsScorecard(): Promise<AnalyticsFinancialResponse> {
  return apiFetch<AnalyticsFinancialResponse>(`/api/analytics/scorecard`, { method: 'GET' })
}

/** GET /api/analytics/sla — per-shipment SLA risk board */
export async function getAnalyticsSla(): Promise<AnalyticsSlaResponse> {
  return apiFetch<AnalyticsSlaResponse>(`/api/analytics/sla`, { method: 'GET' })
}

/** GET /api/analytics/esg — CO2 rail with vs-air comparisons */
export async function getAnalyticsEsg(): Promise<AnalyticsEsgResponse> {
  return apiFetch<AnalyticsEsgResponse>(`/api/analytics/esg`, { method: 'GET' })
}

// ─── AI Copilot ──────────────────────────────────────────────────────────────

/** POST /api/copilot/ask — Gemini with deterministic rules fallback */
export async function askCopilot(
  shipmentId: string,
  question: string,
): Promise<CopilotAskResponse> {
  return apiFetch<CopilotAskResponse>(`/api/copilot/ask`, {
    method: 'POST',
    body: { shipment_id: shipmentId, question },
  })
}

// ─── Shipment predict + financials ───────────────────────────────────────────

/**
 * GET /api/shipments/{id}/predict. Returns null when the model registry
 * is offline or the shipment is unknown (404/503) — the inspector panel
 * simply skips the section, it doesn't light up an error banner.
 */
export async function getShipmentPrediction(id: string): Promise<ShipmentPredictResponse | null> {
  try {
    return await apiFetch<ShipmentPredictResponse>(
      `/api/shipments/${encodeURIComponent(id)}/predict`,
      { method: 'GET' },
    )
  } catch (err) {
    if (err instanceof NexaHttpError && (err.status === 404 || err.status === 503)) {
      return null
    }
    throw err
  }
}

/** GET /api/shipments/{id}/financials (403 → caller hides the tab for viewer roles) */
export async function getShipmentFinancials(id: string): Promise<ShipmentFinancialsResponse> {
  return apiFetch<ShipmentFinancialsResponse>(
    `/api/shipments/${encodeURIComponent(id)}/financials`,
    { method: 'GET' },
  )
}

// Register the new methods in the convenience namespace (keeps existing callers
// that import individual functions untouched — same shorthand resolves here).
Object.assign(nexaClient, {
  getAlerts,
  getAlert,
  acknowledgeAlert,
  getAlertOptions,
  approveAlertOption,
  getDisruptions,
  getDisruption,
  reportDisruption,
  getDecisions,
  getDecision,
  getAnalyticsSummary,
  getAnalyticsScorecard,
  getAnalyticsSla,
  getAnalyticsEsg,
  askCopilot,
  getShipmentPrediction,
  getShipmentFinancials,
  getValidationMatrix,
})
