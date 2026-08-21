export type RiskLevel = 'green' | 'yellow' | 'orange' | 'red'

export interface LocationItem {
  id: string
  name: string
  kind: string
  latitude: number
  longitude: number
  radius_km: number
  is_active: boolean
  created_at: string
  // Talhão support (FASE 26, ADR-0022) — present → this location is a plot
  // inside the parent farm (`parent_location_id`), and `crop` is a
  // free-form culture label (soja, milho, café...).
  parent_location_id: string | null
  crop: string | null
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

export interface ForecastPoint {
  time: string
  temperature_c: number | null
  temperature_min_c: number | null
  precipitation_probability: number | null
  precipitation_mm: number | null
  // Open-Meteo-exclusive (FASE 25, ADR-0021) — other sources leave these
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

export interface CreateLocationInput {
  name: string
  kind?: string
  latitude: number
  longitude: number
  radius_km?: number
  parent_location_id?: string
  crop?: string
}
