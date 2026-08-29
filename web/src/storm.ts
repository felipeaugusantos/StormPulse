/** Pure storm-signal helpers — mirrors agro.ts's pattern (FASE 25,
 * ADR-0021). CAPE thresholds match REDEMET's own 4-tier classification
 * (Fraca/Moderada/Forte/Extremo), an industry-standard scale. Storm ETA is
 * a simple projection from the satellite tracker's already-computed
 * speed/direction — not a forecast model, just "if this cell keeps moving
 * the way it's moving, when would it reach here." */

export type CapeLevel = 'weak' | 'moderate' | 'strong' | 'extreme'

export function classifyCape(capeJkg: number): CapeLevel {
  if (capeJkg < 1000) return 'weak'
  if (capeJkg < 2500) return 'moderate'
  if (capeJkg < 4000) return 'strong'
  return 'extreme'
}

export const CAPE_LABEL: Record<CapeLevel, string> = {
  weak: 'fraca',
  moderate: 'moderada',
  strong: 'forte',
  extreme: 'extrema',
}

const EARTH_RADIUS_KM = 6371

function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

function toDeg(rad: number): number {
  return (rad * 180) / Math.PI
}

/** Great-circle distance between two points, km. */
export function haversineDistanceKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/** Initial bearing from point 1 to point 2, degrees (0=N, 90=E, ...). */
export function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLon = toRad(lon2 - lon1)
  const y = Math.sin(dLon) * Math.cos(toRad(lat2))
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLon)
  return (toDeg(Math.atan2(y, x)) + 360) % 360
}

/** How far off the cell's actual heading a location is from "directly
 * ahead" — 0° = dead-on, 180° = moving straight away. */
function headingOffsetDeg(cellDirectionDeg: number, bearingToLocationDeg: number): number {
  const diff = Math.abs(cellDirectionDeg - bearingToLocationDeg) % 360
  return diff > 180 ? 360 - diff : diff
}

export interface StormEta {
  distanceKm: number
  etaMinutes: number
}

/** Estimated arrival time of a moving cell at a location, assuming it
 * holds its current speed/direction. Returns `null` when the cell isn't
 * heading roughly toward the location (>45° off) or has no meaningful
 * speed — a straight-line projection is misleading past that, so it's
 * honestly omitted rather than shown as a wrong number. */
export function estimateStormEta(
  cellLatitude: number,
  cellLongitude: number,
  cellSpeedKmh: number | null,
  cellDirectionDeg: number | null,
  targetLatitude: number,
  targetLongitude: number,
): StormEta | null {
  if (cellSpeedKmh == null || cellDirectionDeg == null || cellSpeedKmh <= 0) return null

  const distanceKm = haversineDistanceKm(
    cellLatitude,
    cellLongitude,
    targetLatitude,
    targetLongitude,
  )
  const bearingToTarget = bearingDeg(cellLatitude, cellLongitude, targetLatitude, targetLongitude)
  const offset = headingOffsetDeg(cellDirectionDeg, bearingToTarget)
  if (offset > 45) return null

  const etaMinutes = (distanceKm / cellSpeedKmh) * 60
  return { distanceKm, etaMinutes }
}
