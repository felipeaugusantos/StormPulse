import { API_URL } from './config'
import * as authStorage from './authStorage'
import type {
  AlertItem,
  CreateLocationInput,
  CurrentConditions,
  Forecast,
  LocationItem,
  RainfallHistory,
  SprayWindow,
  StormRisk,
  UpdateLocationInput,
} from './types'

const V1 = `${API_URL}/api/v1`

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
  refresh_token: string
}

// The access token expires every 15 minutes (ACCESS_TOKEN_EXPIRE_MINUTES) —
// without this, the app would silently log the user out mid-session. On a
// 401, exchange the refresh token (7-day expiry) for a new pair and retry
// the request once; only surface the 401 (and let the caller log out) if
// the refresh itself fails — meaning the refresh token is gone/expired too,
// a real "please log in again." Mirrors web/src/api.ts's same pattern.
let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  // Shared lock: concurrent 401s (e.g. several screens' parallel requests
  // all expiring at once) must trigger exactly one /auth/refresh call, not
  // one per failed request — every caller awaits the same in-flight promise.
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    const refreshToken = await authStorage.getRefreshToken()
    if (!refreshToken) throw new ApiError(401, 'Sessão expirada')

    const res = await fetch(`${V1}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Platform': 'mobile' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) {
      await authStorage.clearTokens()
      throw new ApiError(401, 'Sessão expirada')
    }
    const data = (await res.json()) as TokenPair
    await authStorage.setTokenPair(data.access_token, data.refresh_token)
    return data.access_token
  })()

  try {
    return await refreshInFlight
  } finally {
    refreshInFlight = null
  }
}

async function request<T>(path: string, init: RequestInit = {}, isRetry = false): Promise<T> {
  const token = await authStorage.getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    // Backend hardening Fase 4 (ADR-0045): REFRESH_COOKIE_ENABLED defaults
    // to true now — without this header the backend can't tell mobile
    // apart from the web dashboard and would strip refresh_token from the
    // response body, breaking mobile's SecureStore-based session.
    'X-Client-Platform': 'mobile',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${V1}${path}`, { ...init, headers })
  if (!res.ok) {
    // Never try to refresh the refresh call itself, or a plain login
    // attempt (a real bad password is a 401 too, not an expired session) —
    // that would recurse into /auth/refresh from inside /auth/refresh.
    const isAuthEndpoint = path.startsWith('/auth/')
    if (res.status === 401 && !isRetry && !isAuthEndpoint) {
      await refreshAccessToken()
      return request<T>(path, init, true)
    }
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* ignore non-JSON errors */
    }
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

/** Whether there's a session to resume — checked at app boot, independent
 * of whether the (short-lived) access token has already expired. */
export const hasSession = authStorage.hasSession

/** Creates the account, then immediately logs in with the same credentials
 * — /auth/register only returns the created user (201), never tokens, so a
 * session still has to be established the normal way right after. Mirrors
 * web/src/api.ts's register(). */
export async function register(
  email: string,
  password: string,
  fullName?: string,
): Promise<void> {
  await request<void>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, full_name: fullName || null }),
  })
  await login(email, password)
}

export async function login(email: string, password: string): Promise<void> {
  const data = await request<TokenPair>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  await authStorage.setTokenPair(data.access_token, data.refresh_token)
}

export async function logout(): Promise<void> {
  await authStorage.clearTokens()
}

export const api = {
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
  risk: (locationId: string) => request<StormRisk>(`/locations/${locationId}/risk`),
  forecast: (locationId: string) => request<Forecast>(`/locations/${locationId}/forecast`),
  // Always Open-Meteo, bypassing INMET/CPTEC (ADR-0020) — the only source
  // with a real numeric rain forecast, needed for trafficability/water
  // balance/CAPE/etc.
  rainForecast: (locationId: string) =>
    request<Forecast>(`/locations/${locationId}/agro/rain-forecast`),
  currentConditions: (locationId: string) =>
    request<CurrentConditions>(`/locations/${locationId}/current`),
  sprayWindow: (locationId: string) =>
    request<SprayWindow>(`/locations/${locationId}/agro/spray-window`),
  rainfall: (locationId: string) =>
    request<RainfallHistory>(`/locations/${locationId}/agro/rainfall`),
  registerExpoPushToken: (expo_push_token: string) =>
    request<void>('/users/me/push-subscription/expo', {
      method: 'POST',
      body: JSON.stringify({ expo_push_token }),
    }),
  deleteExpoPushToken: (expo_push_token: string) =>
    request<void>('/users/me/push-subscription/expo', {
      method: 'DELETE',
      body: JSON.stringify({ expo_push_token }),
    }),
}
