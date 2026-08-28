import type {
  AdminAuditLogList,
  AdminRawFrameList,
  AdminStats,
  AdminTenantList,
  AdminUser,
  AdminUserList,
  AlertItem,
  ApiKey,
  ApiKeyCreated,
  ConvectiveWatch,
  CurrentConditions,
  Forecast,
  LightningStrike,
  LocationItem,
  LocationRisk,
  Me,
  NdviReading,
  PipelineHealth,
  PushSubscriptionInput,
  RainfallHistory,
  ReadyStatus,
  SatelliteImageMeta,
  SprayWindow,
  StormCell,
  WarningItem,
  WeeklyReport,
  ZarcWindow,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const V1 = `${BASE}/api/v1`

// Hardening Fase 4 (ADR-0045): the refresh token is never handled by this
// module at all anymore — it's an HttpOnly cookie the backend sets
// (REFRESH_COOKIE_ENABLED=true by default now that HTTPS + same-origin are
// both in place, ADR-0038/0039) and the browser attaches automatically.
// The access token lives ONLY in memory (a module-level variable) — never
// localStorage, never anything JS can leave lying around after the tab
// closes.
let accessToken: string | null = null

export function getToken(): string | null {
  return accessToken
}
function setToken(token: string): void {
  accessToken = token
}
export function clearToken(): void {
  accessToken = null
}

// One-time migration: anyone who used the app before this change has a
// real, live refresh token sitting in localStorage. Nothing here reads
// those keys anymore, but leaving a valid credential parked in
// localStorage indefinitely is exactly the exposure this phase removes —
// clear them on load. Wrapped in try/catch: localStorage can throw in some
// privacy-mode/embedded contexts, and this cleanup must never block the
// app from starting.
try {
  localStorage.removeItem('stormpulse.access_token')
  localStorage.removeItem('stormpulse.refresh_token')
} catch {
  /* no localStorage available — nothing to migrate away from */
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

interface TokenPair {
  access_token: string
  refresh_token: string | null
}

// The access token expires every 15 minutes (ACCESS_TOKEN_EXPIRE_MINUTES) —
// a user actively using the dashboard would otherwise get logged out every
// 15 minutes. On a 401, silently exchange the refresh cookie for a new
// access token and retry the request once; only surface the 401 (and let
// the caller log out) if the refresh itself fails — meaning the cookie is
// gone/expired too, a real "please log in again."
let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    const res = await fetch(`${V1}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include', // send the HttpOnly refresh cookie
      body: JSON.stringify({}),
    })
    if (!res.ok) {
      clearToken()
      throw new ApiError(401, 'Sessão expirada')
    }
    const data = (await res.json()) as TokenPair
    setToken(data.access_token)
    return data.access_token
  })()

  try {
    return await refreshInFlight
  } finally {
    refreshInFlight = null
  }
}

/** Called once, at app boot: exchanges the HttpOnly refresh cookie (if the
 * browser still has a valid one) for a fresh access token, without the user
 * needing to log in again. Never throws — a missing/expired/blocked cookie
 * is a completely ordinary "please log in" state, not an error; the caller
 * just gets `false` and shows the login screen. */
export async function initSession(): Promise<boolean> {
  try {
    await refreshAccessToken()
    return true
  } catch {
    return false
  }
}

async function request<T>(path: string, init: RequestInit = {}, isRetry = false): Promise<T> {
  const token = getToken()
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${V1}${path}`, { ...init, headers, credentials: 'include' })
  if (!res.ok) {
    // Never try to refresh the refresh call itself, or a plain login
    // attempt (a real bad password is a 401 too, not an expired session).
    const isAuthEndpoint = path.startsWith('/auth/')
    if (res.status === 401 && !isRetry && !isAuthEndpoint) {
      await refreshAccessToken()
      return request<T>(path, init, true)
    }
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* ignore non-JSON errors */
    }
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

/** Same auth/retry contract as `request`, but for a binary response (item
 * 2's PDF export) — never tries to parse the body as JSON. */
async function requestBlob(path: string, isRetry = false): Promise<Blob> {
  const token = getToken()
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${V1}${path}`, { headers, credentials: 'include' })
  if (!res.ok) {
    if (res.status === 401 && !isRetry) {
      await refreshAccessToken()
      return requestBlob(path, true)
    }
    throw new ApiError(res.status, `HTTP ${res.status}`)
  }
  return res.blob()
}

/** Creates the account, then immediately logs in with the same credentials
 * — /auth/register only returns the created user (201), never tokens, so a
 * session still has to be established the normal way right after. */
/** Returns `true` if the auto-login after registration succeeded. `false`
 * means the account was created but the caller must show the login form
 * instead — happens when hCaptcha is configured, since the token just
 * spent on /auth/register is single-use and can't be reused for the
 * follow-up /auth/login call. Registration itself having failed still
 * throws normally (never swallowed). */
export async function register(
  email: string,
  password: string,
  fullName?: string,
  modules?: { storm: boolean; agro: boolean },
  acceptTerms?: boolean,
  captchaToken?: string,
): Promise<boolean> {
  await request<void>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
      full_name: fullName || null,
      storm_module: modules?.storm ?? true,
      agro_module: modules?.agro ?? false,
      accept_terms: acceptTerms ?? false,
      captcha_token: captchaToken || null,
    }),
  })
  try {
    await login(email, password)
    return true
  } catch {
    return false
  }
}

export async function login(email: string, password: string, captchaToken?: string): Promise<void> {
  const data = await request<TokenPair>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, captcha_token: captchaToken || null }),
  })
  setToken(data.access_token)
}

export async function verifyEmail(token: string): Promise<void> {
  await request<void>('/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) })
}

export async function resendVerification(): Promise<{ sent: boolean }> {
  return request<{ sent: boolean }>('/auth/resend-verification', { method: 'POST' })
}

export async function forgotPassword(email: string): Promise<void> {
  await request<void>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await request<void>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  })
}

export async function loginWithGoogle(idToken: string): Promise<void> {
  const data = await request<TokenPair>('/auth/google', {
    method: 'POST',
    body: JSON.stringify({ id_token: idToken }),
  })
  setToken(data.access_token)
}

/** Clears the HttpOnly refresh cookie server-side and the in-memory access
 * token locally. Always safe to call, even if the session already expired
 * (the backend's /auth/logout is unconditional and idempotent) — never
 * throws, a failed network call still clears local state. */
export async function logout(): Promise<void> {
  try {
    await fetch(`${V1}/auth/logout`, { method: 'POST', credentials: 'include' })
  } catch {
    /* best-effort — local state is cleared regardless, below */
  } finally {
    clearToken()
  }
}

export interface CreateLocationInput {
  name: string
  kind?: string
  latitude: number
  longitude: number
  radius_km?: number
  // Talhão support (FASE 26) — present → this location is a plot inside
  // the parent farm.
  parent_location_id?: string
  crop?: string
  // Soil texture class (item ZARC, ADR-0069) — `arenoso`/`textura_media`/
  // `argiloso`.
  soil_type?: string
  // Visual-only polygon outline (FASE 27, ADR-0024) — a GeoJSON Polygon
  // serialized as a JSON string.
  boundary_geojson?: string
  // Manual color override (FASE 27, ADR-0025) — `#RRGGBB`.
  color?: string
}

export interface UpdateLocationInput {
  name?: string
  kind?: string
  latitude?: number
  longitude?: number
  radius_km?: number
  is_active?: boolean
  // `null` clears the field (sent explicitly, distinct from omitting the
  // key entirely, which leaves it untouched) — `soil_type` in particular
  // rejects an empty string, it only accepts one of the three valid
  // values or `null`.
  crop?: string | null
  soil_type?: string | null
  boundary_geojson?: string
  color?: string
}

export const api = {
  me: () => request<Me>('/users/me'),
  deleteAccount: () =>
    request<void>('/users/me', { method: 'DELETE', body: JSON.stringify({ confirm: true }) }),
  registerPushSubscription: (data: PushSubscriptionInput) =>
    request<void>('/users/me/push-subscription', { method: 'POST', body: JSON.stringify(data) }),
  createApiKey: (name: string) =>
    request<ApiKeyCreated>('/users/me/api-keys', { method: 'POST', body: JSON.stringify({ name }) }),
  listApiKeys: () =>
    request<{ items: ApiKey[] }>('/users/me/api-keys').then((r) => r.items),
  revokeApiKey: (keyId: string) =>
    request<void>(`/users/me/api-keys/${keyId}`, { method: 'DELETE' }),
  deletePushSubscription: (endpoint: string) =>
    request<void>('/users/me/push-subscription', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint }),
    }),
  storms: () => request<StormCell[]>('/storms?limit=200'),
  locations: () => request<LocationItem[]>('/locations'),
  createLocation: (data: CreateLocationInput) =>
    request<LocationItem>('/locations', { method: 'POST', body: JSON.stringify(data) }),
  updateLocation: (locationId: string, data: UpdateLocationInput) =>
    request<LocationItem>(`/locations/${locationId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteLocation: (locationId: string) =>
    request<void>(`/locations/${locationId}`, { method: 'DELETE' }),
  alerts: () => request<AlertItem[]>('/alerts'),
  // 404 quando nenhuma avaliação de risco foi calculada ainda para o
  // local — caller trata isso como "sem risco por enquanto", não erro.
  risk: (locationId: string) => request<LocationRisk>(`/locations/${locationId}/risk`),
  forecast: (locationId: string) => request<Forecast>(`/locations/${locationId}/forecast`),
  // Always Open-Meteo, bypassing INMET/CPTEC — the only source with a real
  // numeric rain forecast (backend: get_numeric_rain_forecast_provider,
  // ADR-0020). Used specifically where the *amount* of rain coming matters
  // (soil trafficability), not just the temperature strip.
  rainForecast: (locationId: string) =>
    request<Forecast>(`/locations/${locationId}/agro/rain-forecast`),
  currentConditions: (locationId: string) =>
    request<CurrentConditions>(`/locations/${locationId}/current`),
  satelliteWatches: () => request<ConvectiveWatch[]>('/satellite'),
  lightning: () => request<LightningStrike[]>('/lightning'),
  sprayWindow: (locationId: string) =>
    request<SprayWindow>(`/locations/${locationId}/agro/spray-window`),
  rainfall: (locationId: string, days = 15) =>
    request<RainfallHistory>(`/locations/${locationId}/agro/rainfall?days=${days}`),
  // Only ever has data for a talhão with a drawn boundary (FASE 29,
  // ADR-0053) — 404s for a farm-level point or a talhão the background
  // pipeline hasn't checked yet, same "no data" shape as everything else.
  ndvi: (locationId: string) => request<NdviReading>(`/locations/${locationId}/agro/ndvi`),
  // Item "imagem do talhão" — colored NDVI map (green=vigorous,
  // red/brown=stressed), only the latest kept, same "no data" 404 shape
  // as ndvi() above.
  ndviImage: (locationId: string) => requestBlob(`/locations/${locationId}/agro/ndvi-image`),
  // Talhão-only (FASE 32) — 404s for a farm-level point, same shape as ndvi().
  weeklyReport: (locationId: string) =>
    request<WeeklyReport>(`/locations/${locationId}/agro/weekly-report`),
  // Item 2 (ADR-0063) — same data as weeklyReport(), rendered server-side
  // as a downloadable PDF.
  weeklyReportPdf: (locationId: string) =>
    requestBlob(`/locations/${locationId}/agro/weekly-report/pdf`),
  // Item ZARC (ADR-0069) — talhão-only, 404s the same way as ndvi()/
  // weeklyReport() when the talhão has no crop/soil set or no MAPA window
  // matches it.
  zarcWindow: (locationId: string) =>
    request<ZarcWindow>(`/locations/${locationId}/agro/zarc-window`),
  // Cross-tenant platform-admin panel (FASE 28, ADR-0048) — only ever
  // called when `Me.is_platform_admin` is true; the backend 403s otherwise.
  adminUsers: (opts: { search?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.search) params.set('search', opts.search)
    if (opts.limit) params.set('limit', String(opts.limit))
    if (opts.offset) params.set('offset', String(opts.offset))
    const qs = params.toString()
    return request<AdminUserList>(`/admin/users${qs ? `?${qs}` : ''}`)
  },
  adminTenants: (opts: { search?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.search) params.set('search', opts.search)
    if (opts.limit) params.set('limit', String(opts.limit))
    if (opts.offset) params.set('offset', String(opts.offset))
    const qs = params.toString()
    return request<AdminTenantList>(`/admin/tenants${qs ? `?${qs}` : ''}`)
  },
  // FASE 28 Fase 2 (ADR-0049) — is_active/role mutations, always with
  // confirm: true (the backend rejects anything else, mirroring
  // deleteAccount's confirmation gate).
  adminUpdateUser: (userId: string, data: { is_active?: boolean; role?: string }) =>
    request<AdminUser>(`/admin/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ ...data, confirm: true }),
    }),
  adminAuditLog: (opts: { limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.limit) params.set('limit', String(opts.limit))
    if (opts.offset) params.set('offset', String(opts.offset))
    const qs = params.toString()
    return request<AdminAuditLogList>(`/admin/audit-log${qs ? `?${qs}` : ''}`)
  },
  adminStats: () => request<AdminStats>('/admin/stats'),
  adminPipelineHealth: () => request<PipelineHealth[]>('/admin/pipeline-health'),
  // Item 4 (ADR-0065) — raw radar-frame history retained per ingestion cycle.
  adminRawFrames: (opts: { limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.limit) params.set('limit', String(opts.limit))
    if (opts.offset) params.set('offset', String(opts.offset))
    const qs = params.toString()
    return request<AdminRawFrameList>(`/admin/raw-frames${qs ? `?${qs}` : ''}`)
  },
  adminTriggerPipeline: (name: string) =>
    request<{ queued: boolean; name: string }>('/admin/pipeline-health/trigger', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
}

// Radius publicApi's nearby calls query with — wider than the 50km default
// authenticated locations use (that's a tight personal-alert radius);
// visitor mode is an exploratory regional view.
export const VISITOR_SEARCH_RADIUS_KM = 150

// No token required (visitor mode) — same request() helper, it just won't
// attach an Authorization header when there isn't one.
export const publicApi = {
  // Nearby (not the global/unfiltered list endpoints) — the visitor's
  // chosen reference point actually has to change what these show.
  storms: (lat: number, lon: number) =>
    request<StormCell[]>(
      `/public/storms/nearby?lat=${lat}&lon=${lon}&radius_km=${VISITOR_SEARCH_RADIUS_KM}`,
    ),
  warnings: (lat: number, lon: number) =>
    request<WarningItem[]>(`/public/warnings?lat=${lat}&lon=${lon}`),
  satelliteWatches: (lat: number, lon: number) =>
    request<ConvectiveWatch[]>(
      `/public/satellite/watches/nearby?lat=${lat}&lon=${lon}&radius_km=${VISITOR_SEARCH_RADIUS_KM}`,
    ),
  lightning: (lat: number, lon: number) =>
    request<LightningStrike[]>(
      `/public/lightning/nearby?lat=${lat}&lon=${lon}&radius_km=${VISITOR_SEARCH_RADIUS_KM}`,
    ),
  // No cycle has run yet (or SATELLITE_ENABLED=false) is a normal, common
  // state — treated as "no image", not an error, same spirit as an empty
  // watches list.
  satelliteImage: async (): Promise<SatelliteImageMeta | null> => {
    try {
      return await request<SatelliteImageMeta>('/public/satellite/image')
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null
      throw err
    }
  },
}

// The MapLibre `image` source fetches this URL directly (no Authorization
// header attached) — the endpoint must be, and is, public. `capturedAt` in
// the query string busts the browser cache when a new frame is available.
export function satelliteImagePngUrl(capturedAt: string): string {
  return `${V1}/public/satellite/image.png?t=${encodeURIComponent(capturedAt)}`
}

// Health/readiness live at the API root, not under /api/v1.
export async function readiness(): Promise<ReadyStatus> {
  const res = await fetch(`${BASE}/ready`)
  return (await res.json()) as ReadyStatus
}
