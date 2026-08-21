export type RiskLevel = 'green' | 'yellow' | 'orange' | 'red'
export type StormSeverity = 'weak' | 'moderate' | 'strong' | 'severe'

export interface Me {
  id: string
  tenant_id: string
  email: string
  full_name: string | null
  role: string
  is_active: boolean
  created_at: string
}

export interface StormCell {
  id: string
  detected_at: string
  latitude: number
  longitude: number
  severity: StormSeverity
  max_reflectivity: number | null
  average_reflectivity: number | null
  area_km2: number | null
  is_mock: boolean
}

export interface LocationItem {
  id: string
  name: string
  kind: string
  latitude: number
  longitude: number
  radius_km: number
  is_active: boolean
  created_at: string
  alert_preferences: { alert_type: string; enabled: boolean }[]
}

export interface AlertItem {
  id: string
  location_id: string
  storm_cell_id: string | null
  event_type: string
  level: RiskLevel
  title: string
  message: string
  created_at: string
}

export interface ReadyStatus {
  status: 'ready' | 'not_ready'
  checks: Record<string, 'ok' | 'error' | 'skipped'>
}

export interface ForecastPoint {
  time: string
  temperature_c: number | null
  temperature_min_c: number | null
  precipitation_probability: number | null
  precipitation_mm: number | null
  // Open-Meteo-exclusive (FASE 25, ADR-0021) — INMET/CPTEC leave these
  // `null`, never approximated from something else.
  temperature_mean_c: number | null
  humidity_mean_percent: number | null
  humidity_max_percent: number | null
  wind_gusts_max_kmh: number | null
  evapotranspiration_mm: number | null
  cape_max_jkg: number | null
}

export interface Forecast {
  latitude: number
  longitude: number
  points: ForecastPoint[]
}

export interface WarningItem {
  issued_at: string
  kind: string
  severity: string
  description: string
}

export interface ConvectiveWatch {
  id: string
  first_detected_at: string
  detected_at: string
  latitude: number
  longitude: number
  min_brightness_temp_k: number
  area_km2: number | null
  speed_kmh: number | null
  direction_deg: number | null
  is_active: boolean
  is_mock: boolean
  experimental: boolean
}

export interface LightningStrike {
  id: string
  detected_at: string
  latitude: number
  longitude: number
  is_mock: boolean
}

export interface SatelliteImageMeta {
  captured_at: string
  bbox: [number, number, number, number]
  band: string
  width: number
  height: number
}

export interface SprayWindow {
  wind_kmh: number | null
  wind_gusts_kmh: number | null
  max_wind_kmh: number
  rain_probability_percent: number | null
  rain_expected_mm: number | null
  max_rain_probability_percent: number
  humidity_percent: number | null
  inversion_risk: boolean
  safe: boolean | null
}

export interface DailyRainfall {
  date: string
  total_mm: number
}

export interface RainfallHistory {
  latitude: number
  longitude: number
  daily: DailyRainfall[]
}

export interface Provenance {
  source_name: string
  source_kind: string
  is_mock: boolean
}

export interface CurrentConditions {
  provenance: Provenance
  observed_at: string
  latitude: number
  longitude: number
  temperature_c: number | null
  wind_kmh: number | null
  wind_gusts_kmh: number | null
  precipitation_mm: number | null
}

export interface CitySearchResult {
  label: string
  latitude: number
  longitude: number
}

export interface PushSubscriptionInput {
  endpoint: string
  keys: { p256dh: string; auth: string }
}
