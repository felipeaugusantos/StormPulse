import type {
  AlertItem,
  ConvectiveWatch,
  CurrentConditions,
  Forecast,
  LocationItem,
  Me,
  RainfallHistory,
  ReadyStatus,
  SatelliteImageMeta,
  SprayWindow,
  StormCell,
  WarningItem,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const V1 = `${BASE}/api/v1`

const TOKEN_KEY = 'stormpulse.access_token'
const REFRESH_TOKEN_KEY = 'stormpulse.refresh_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}
function setRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
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
  refresh_token: string
}

// The access token expires every 15 minutes (ACCESS_TOKEN_EXPIRE_MINUTES) —
// a user actively using the dashboard would otherwise get logged out every
// 15 minutes. On a 401, silently exchange the refresh token (7-day expiry)
// for a new pair and retry the request once; only surface the 401 (and let
// the caller log out) if the refresh itself fails — meaning the refresh
// token is gone/expired too, a real "please log in again."
let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight
  const refreshToken = getRefreshToken()
  if (!refreshToken) throw new ApiError(401, 'Sessão expirada')

  refreshInFlight = (async () => {
    const res = await fetch(`${V1}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) {
      clearToken()
      throw new ApiError(401, 'Sessão expirada')
    }
    const data = (await res.json()) as TokenPair
    setToken(data.access_token)
    setRefreshToken(data.refresh_token)
    return data.access_token
  })()

  try {
    return await refreshInFlight
  } finally {
    refreshInFlight = null
  }
}

async function request<T>(path: string, init: RequestInit = {}, isRetry = false): Promise<T> {
  const token = getToken()
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${V1}${path}`, { ...init, headers })
  if (!res.ok) {
    // Never try to refresh the refresh call itself, or a plain login
    // attempt (a real bad password is a 401 too, not an expired session).
    const isAuthEndpoint = path.startsWith('/auth/')
    if (res.status === 401 && !isRetry && !isAuthEndpoint && getRefreshToken()) {
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

export async function login(email: string, password: string): Promise<string> {
  const data = await request<TokenPair>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setRefreshToken(data.refresh_token)
  return data.access_token
}

export async function loginWithGoogle(idToken: string): Promise<string> {
  const data = await request<TokenPair>('/auth/google', {
    method: 'POST',
    body: JSON.stringify({ id_token: idToken }),
  })
  setRefreshToken(data.refresh_token)
  return data.access_token
}

export interface CreateLocationInput {
  name: string
  kind?: string
  latitude: number
  longitude: number
  radius_km?: number
}

export const api = {
  me: () => request<Me>('/users/me'),
  storms: () => request<StormCell[]>('/storms?limit=200'),
  locations: () => request<LocationItem[]>('/locations'),
  createLocation: (data: CreateLocationInput) =>
    request<LocationItem>('/locations', { method: 'POST', body: JSON.stringify(data) }),
  deleteLocation: (locationId: string) =>
    request<void>(`/locations/${locationId}`, { method: 'DELETE' }),
  alerts: () => request<AlertItem[]>('/alerts'),
  forecast: (locationId: string) => request<Forecast>(`/locations/${locationId}/forecast`),
  currentConditions: (locationId: string) =>
    request<CurrentConditions>(`/locations/${locationId}/current`),
  satelliteWatches: () => request<ConvectiveWatch[]>('/satellite'),
  sprayWindow: (locationId: string) =>
    request<SprayWindow>(`/locations/${locationId}/agro/spray-window`),
  rainfall: (locationId: string, days = 15) =>
    request<RainfallHistory>(`/locations/${locationId}/agro/rainfall?days=${days}`),
}

// No token required (visitor mode) — same request() helper, it just won't
// attach an Authorization header when there isn't one.
export const publicApi = {
  storms: () => request<StormCell[]>('/public/storms?limit=200'),
  warnings: (lat: number, lon: number) =>
    request<WarningItem[]>(`/public/warnings?lat=${lat}&lon=${lon}`),
  satelliteWatches: () => request<ConvectiveWatch[]>('/public/satellite/watches'),
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
