export type RiskLevel = 'green' | 'yellow' | 'orange' | 'red'
export type StormSeverity = 'weak' | 'moderate' | 'strong' | 'severe'

// Materialized risk assessment for one location (GET /locations/:id/risk).
export interface LocationRisk {
  id: string
  location_id: string
  storm_cell_id: string | null
  severity: RiskLevel
  rain_risk: number
  wind_risk: number
  hail_risk: number
  lightning_risk: number
  storm_distance_km: number | null
  storm_speed_kmh: number | null
  eta_minutes: number | null
  computed_at: string
  is_mock: boolean
  experimental: boolean
  // FASE 9 (ADR-0060) — null quando ANTHROPIC_API_KEY não está
  // configurada, a geração ainda não rodou, ou a severidade é "green"
  // (nada a explicar).
  ai_summary: string | null
}

export interface Me {
  id: string
  tenant_id: string
  email: string
  full_name: string | null
  role: string
  is_active: boolean
  is_platform_admin: boolean
  created_at: string
  // Module selection (FASE 30), chosen at registration — which tabs the
  // dashboard should show for this tenant.
  storm_module_enabled: boolean
  agro_module_enabled: boolean
  // FASE 8 — informativo, nunca bloqueia login. Drives a "confirme seu
  // e-mail" banner no Dashboard.
  email_verified: boolean
}

// API pública/externa (item 1, ADR-0062) — gestão de chaves.
export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKey {
  // Só vem preenchido na resposta de criação — nunca mais depois disso.
  key: string
}

// Cross-tenant platform-admin panel (FASE 28, ADR-0048) — only ever
// fetched when `Me.is_platform_admin` is true.
export interface AdminUser {
  id: string
  tenant_id: string
  tenant_name: string
  email: string
  full_name: string | null
  role: string
  is_active: boolean
  is_platform_admin: boolean
  created_at: string
  last_login_at: string | null
}

export interface AdminUserList {
  items: AdminUser[]
  total: number
}

export interface AdminTenant {
  id: string
  name: string
  slug: string
  is_active: boolean
  created_at: string
  user_count: number
  location_count: number
}

export interface AdminTenantList {
  items: AdminTenant[]
  total: number
}

export interface AdminAuditLogEntry {
  id: string
  actor_email: string
  action: string
  target_email: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface AdminAuditLogList {
  items: AdminAuditLogEntry[]
  total: number
}

export interface AdminStats {
  total_tenants: number
  total_users: number
  active_users_7d: number
  active_users_30d: number
  total_locations: number
  alerts_last_30d: number
}

// Raw radar-frame history (item 4, ADR-0065) — exactly what the active
// provider returned each ingestion cycle, before StormEngine clusters it
// into a StormCell.
export interface AdminRawFrame {
  id: string
  weather_source_id: string
  captured_at: string
  is_mock: boolean
  meta: { source_name?: string; cells?: Record<string, unknown>[] }
}

export interface AdminRawFrameList {
  items: AdminRawFrame[]
  total: number
}

export interface PipelineHealth {
  name: string
  last_updated_at: string | null
  expected_interval_seconds: number
  stale: boolean
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
  // Motion of the cell's active track, and a 1h straight-line projection
  // from it — null when the cell has no active track with a computed
  // trajectory yet (never fabricated, see backend/app/storms/service.py).
  speed_kmh: number | null
  direction_deg: number | null
  projected_latitude_1h: number | null
  projected_longitude_1h: number | null
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
  // Talhão support (FASE 26) — present → this location is a plot inside
  // the parent farm (`parent_location_id`), and `crop` is a free-form
  // culture label (soja, milho, café...).
  parent_location_id: string | null
  crop: string | null
  // Soil texture class (item ZARC, ADR-0069) — needed to match a talhão's
  // crop+município against the right ZARC planting window.
  soil_type: string | null
  // Visual-only polygon outline (FASE 27, ADR-0024) — a GeoJSON Polygon
  // serialized as a JSON string, or `null` when this location has no
  // drawn boundary. Never used for weather/agro lookups.
  boundary_geojson: string | null
  // Manual color override (FASE 27, ADR-0025) — when `null`, the map
  // derives a color from `crop` instead (`cropColor()`).
  color: string | null
  // Derived from `boundary_geojson` by the backend, never stored — `null`
  // when there's no drawn boundary.
  area_ha: number | null
}

// NDVI per talhão (FASE 29, ADR-0053) — only ever meaningful for a plot
// with a drawn boundary; a farm-level point has no polygon to average
// vegetation-index pixels over.
export interface NdviReading {
  observed_at: string
  // The backend column is NOT NULL, but a crash in production (2026-08-28)
  // proved a `null` reaches the client for at least one real reading —
  // treated as possible here rather than re-asserting a guarantee that
  // demonstrably didn't hold.
  ndvi_mean: number | null
  valid_pixel_percent: number
  is_mock: boolean
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

// One INPE DETER/PRODES alert intersecting a talhão's drawn boundary
// (item DETER).
export interface DeforestationAlert {
  source: string // "DETER-AMZ" | "PRODES-CERRADO"
  classname: string
  detected_at: string | null
  area_ha: number | null
  municipio: string | null
  uf: string | null
}

// Result of checking a talhão against INPE's own deforestation registries
// (item DETER) — `checked_sources` lists which of DETER-AMZ/PRODES-CERRADO
// the background pipeline last successfully queried; a source missing
// here was never checked or its last attempt failed, never "checked, no
// alerts". Only covers the Amazônia/Cerrado biomes.
export interface DeforestationCheck {
  checked_sources: string[]
  last_checked_at: string | null
  alerts: DeforestationAlert[]
}

// Regional soil-wetness context from NASA POWER (item NASA) — a
// model-based estimate (~50km native resolution), never a per-talhão
// measurement like NDVI.
export interface SoilMoisture {
  observed_at: string
  surface_wetness_percent: number
  root_zone_wetness_percent: number
  profile_wetness_percent: number
  is_mock: boolean
}

// Weekly report per talhão (FASE 32) — last 7 full days of rainfall,
// agro alerts and NDVI readings, meant to be printed/shown to an
// agronomist or bank.
export interface WeeklyReport {
  location_id: string
  location_name: string
  crop: string | null
  // Derived from the talhão's drawn boundary — `null` without one.
  area_ha: number | null
  period_start: string
  period_end: string
  rainfall_total_mm: number
  dry_days_count: number
  alerts: AlertItem[]
  ndvi_readings: NdviReading[]
  // `null` when the check is disabled or never ran for this talhão yet.
  deforestation: DeforestationCheck | null
  // `null` when the source is disabled or unavailable this time.
  soil_moisture: SoilMoisture | null
  generated_at: string
  // Short natural-language reading of the numbers above, generated by
  // Claude — `null` when unconfigured or the call failed.
  ai_summary: string | null
}

// ZARC planting-window info for a talhão (item ZARC, ADR-0069) — purely
// informational, never generates an alert on its own.
export interface ZarcMatch {
  cultura: string
  cod_ciclo: number
  ciclo_label: string
  safra_ini: number
  safra_fin: number
  portaria: string | null
  decendios: number[]
}

export interface ZarcWindow {
  location_id: string
  geocodigo: string
  municipio: string
  uf: string
  matches: ZarcMatch[]
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
  wind_direction_deg: number | null
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
