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
