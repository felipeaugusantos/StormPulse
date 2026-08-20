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
