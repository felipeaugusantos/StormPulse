import type {
  AlertItem,
  ConvectiveWatch,
  Forecast,
  LocationItem,
  Me,
  ReadyStatus,
  StormCell,
  WarningItem,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const V1 = `${BASE}/api/v1`

const TOKEN_KEY = 'stormpulse.access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${V1}${path}`, { ...init, headers })
  if (!res.ok) {
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
  const data = await request<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return data.access_token
}

export async function loginWithGoogle(idToken: string): Promise<string> {
  const data = await request<{ access_token: string }>('/auth/google', {
    method: 'POST',
    body: JSON.stringify({ id_token: idToken }),
  })
  return data.access_token
}

export const api = {
  me: () => request<Me>('/users/me'),
  storms: () => request<StormCell[]>('/storms?limit=200'),
  locations: () => request<LocationItem[]>('/locations'),
  alerts: () => request<AlertItem[]>('/alerts'),
  forecast: (locationId: string) => request<Forecast>(`/locations/${locationId}/forecast`),
  satelliteWatches: () => request<ConvectiveWatch[]>('/satellite'),
}

// No token required (visitor mode) — same request() helper, it just won't
// attach an Authorization header when there isn't one.
export const publicApi = {
  storms: () => request<StormCell[]>('/public/storms?limit=200'),
  warnings: (lat: number, lon: number) =>
    request<WarningItem[]>(`/public/warnings?lat=${lat}&lon=${lon}`),
  satelliteWatches: () => request<ConvectiveWatch[]>('/public/satellite/watches'),
}

// Health/readiness live at the API root, not under /api/v1.
export async function readiness(): Promise<ReadyStatus> {
  const res = await fetch(`${BASE}/ready`)
  return (await res.json()) as ReadyStatus
}
