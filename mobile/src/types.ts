export type RiskLevel = 'green' | 'yellow' | 'orange' | 'red'

export interface LocationItem {
  id: string
  name: string
  kind: string
  latitude: number
  longitude: number
  radius_km: number
}

export interface StormRisk {
  id: string
  location_id: string
  severity: RiskLevel
  rain_risk: number
  wind_risk: number
  hail_risk: number
  lightning_risk: number
  storm_distance_km: number | null
  storm_speed_kmh: number | null
  eta_minutes: number | null
  is_mock: boolean
  experimental: boolean
}

export interface AlertItem {
  id: string
  location_id: string
  event_type: string
  level: RiskLevel
  title: string
  message: string
  created_at: string
}
