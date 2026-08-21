import AsyncStorage from '@react-native-async-storage/async-storage'
import { API_URL } from './config'
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
const TOKEN_KEY = 'stormpulse.access_token'

let cachedToken: string | null = null

export async function loadToken(): Promise<string | null> {
  if (cachedToken) return cachedToken
  cachedToken = await AsyncStorage.getItem(TOKEN_KEY)
  return cachedToken
}

export async function saveToken(token: string): Promise<void> {
  cachedToken = token
  await AsyncStorage.setItem(TOKEN_KEY, token)
}

export async function clearToken(): Promise<void> {
  cachedToken = null
  await AsyncStorage.removeItem(TOKEN_KEY)
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
  const token = await loadToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${V1}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* ignore */
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
  await saveToken(data.access_token)
  return data.access_token
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
