/** Presentation helpers shared by satellite-watch panels (Dashboard, VisitorView).
 *
 * Buckets are rule-based on the real measured brightness temperature — same
 * "deterministic, not fabricated" spirit as the storm severity labels, just
 * applied to a different physical quantity (cloud-top IR temperature instead
 * of reflectivity).
 */

const DIRECTIONS = ['N', 'NE', 'L', 'SE', 'S', 'SO', 'O', 'NO']

export function kelvinToCelsius(kelvin: number): number {
  return kelvin - 273.15
}

/** Convective intensity label from cloud-top temperature (colder = stronger updraft). */
export function convectiveIntensity(tempKelvin: number): {
  label: string
  className: 'green' | 'yellow' | 'orange' | 'red'
} {
  const c = kelvinToCelsius(tempKelvin)
  if (c <= -65) return { label: 'severa', className: 'red' }
  if (c <= -55) return { label: 'forte', className: 'orange' }
  if (c <= -45) return { label: 'moderada', className: 'yellow' }
  return { label: 'fraca', className: 'green' }
}

const RISK_LEVEL_LABELS: Record<string, string> = {
  green: 'Baixo',
  yellow: 'Moderado',
  orange: 'Alto',
  red: 'Severo',
}

/** Plain-language severity word for a risk-level color code (`green`/
 * `yellow`/`orange`/`red`) — the raw code is an internal identifier, not
 * something an end user should ever see directly. */
export function riskLevelLabel(level: string): string {
  return RISK_LEVEL_LABELS[level] ?? level
}

const ALERT_EVENT_LABELS: Record<string, string> = {
  storm_detected: 'Tempestade detectada',
  storm_approaching: 'Tempestade se aproximando',
  storm_intensified: 'Tempestade se intensificou',
  storm_entered_monitoring_area: 'Tempestade entrou na área monitorada',
  storm_risk_changed: 'Risco de tempestade mudou',
  storm_passed: 'Tempestade passou',
  satellite_watch_detected: 'Observação via satélite',
  satellite_watch_dissipated: 'Observação via satélite dissipada',
  frost_warning: 'Risco de geada',
  dry_spell_warning: 'Sequência sem chuva',
}

/** Plain-language category for an alert's internal event-type code (e.g.
 * `dry_spell_warning`) — falls back to the raw code for any future event
 * type this list hasn't caught up with yet, rather than hiding it. */
export function alertEventLabel(eventType: string): string {
  return ALERT_EVENT_LABELS[eventType] ?? eventType
}

export function cardinalDirection(degrees: number): string {
  const index = Math.round(((degrees % 360) + 360) % 360 / 45) % 8
  return DIRECTIONS[index]
}

/** "há 3 min" / "há 2 h" — coarse, no external dependency. */
export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.max(0, Math.round(diffMs / 60_000))
  if (minutes < 1) return 'agora'
  if (minutes < 60) return `há ${minutes} min`
  const hours = Math.round(minutes / 60)
  return `há ${hours} h`
}
