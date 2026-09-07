/** Pure agro-signal helpers shared by LocationWeatherCard and the Agro
 * panel — mirrors the equivalent backend logic in
 * `backend/workers/agro_pipeline.py` (frost tiers) and reimplements
 * `dry_streak_days` client-side since only raw daily totals are exposed via
 * `/agro/rainfall`, not the computed streak itself (FASE 22, ADR-0018). */

import { formatDateBR, timeUntil } from './format'
import type { DailyRainfall, ForecastPoint } from './types'

export interface FrostDayTiers {
  severe: ForecastPoint[]
  light: ForecastPoint[]
}

/** Same two-threshold idea as Agritempo's frost forecast: severe at/below
 * `severeThresholdC`, light at/below `lightThresholdC` but above severe. */
export function classifyFrostDays(
  points: ForecastPoint[],
  severeThresholdC: number,
  lightThresholdC: number,
): FrostDayTiers {
  const withMin = points.filter((p) => p.temperature_min_c != null)
  const severe = withMin.filter((p) => (p.temperature_min_c as number) <= severeThresholdC)
  const light = withMin.filter(
    (p) =>
      (p.temperature_min_c as number) > severeThresholdC &&
      (p.temperature_min_c as number) <= lightThresholdC,
  )
  return { severe, light }
}

export function formatFrostDays(points: ForecastPoint[]): string {
  return points
    .map((p) => {
      const day = formatDateBR(p.time, { day: '2-digit', month: '2-digit' })
      const temp = p.temperature_min_c != null ? `${p.temperature_min_c.toFixed(1)}°C` : '—'
      return `${day} (${temp})`
    })
    .join(', ')
}

/** Compact "geada em N dias" for the earliest day in `points`, same
 * presentation as storm ETA/ZARC window (Fase 4, ADR-0088) — complements
 * `formatFrostDays` above (which stays the full-list view), doesn't
 * replace it. `null` when `points` is empty (no frost day to point at). */
export function formatFrostDaysAhead(points: ForecastPoint[], now: Date = new Date()): string | null {
  if (points.length === 0) return null
  const earliest = points.reduce((a, b) => (new Date(a.time) < new Date(b.time) ? a : b))
  const minutesUntil = (new Date(earliest.time).getTime() - now.getTime()) / 60_000
  return `geada ${timeUntil(minutesUntil)}`
}

const DAYS_IN_MONTH_NON_LEAP = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

/** Day-of-year (0-indexed) a ZARC `decêndio` starts on — official MAPA
 * convention: 3 ten-day periods per month (days 1-10, 11-20, 21-end-of-
 * month), 36 total, not a calendar-agnostic 1/36th of the year. */
function decendioStartDayOfYear(index: number): number {
  const month = Math.floor(index / 3)
  const periodInMonth = index % 3
  let dayOfYear = 0
  for (let m = 0; m < month; m++) dayOfYear += DAYS_IN_MONTH_NON_LEAP[m]
  return dayOfYear + periodInMonth * 10
}

/** Compact "janela recomendada em N dias" for the next non-zero `decêndio`
 * from `now` — same presentation as storm ETA/frost (Fase 4, ADR-0088).
 * Checks both this year's and next year's occurrence of every recommended
 * decêndio so a window near year-end/January still resolves correctly.
 * `null` when every decêndio is 0 (no recommended window at all for this
 * cultura/solo/município). */
export function formatZarcWindowAhead(decendios: number[], now: Date = new Date()): string | null {
  const nonZeroIndices = decendios.map((v, i) => (v !== 0 ? i : -1)).filter((i) => i !== -1)
  if (nonZeroIndices.length === 0) return null

  const minutesUntil = (index: number, yearOffset: number) => {
    const start = new Date(now.getFullYear() + yearOffset, 0, 1 + decendioStartDayOfYear(index))
    return (start.getTime() - now.getTime()) / 60_000
  }
  const candidates = nonZeroIndices.flatMap((i) => [minutesUntil(i, 0), minutesUntil(i, 1)])
  const soonest = Math.min(...candidates.filter((m) => m >= 0))
  return `janela recomendada ${timeUntil(soonest)}`
}

/** Consecutive most-recent days with rainfall below `thresholdMm`. Stops at
 * the first gap in the data (never assumes a missing day is dry) or the
 * first day at/above the threshold — same rule as the backend's
 * `dry_streak_days`. */
export function dryStreakDays(daily: DailyRainfall[], thresholdMm: number): number {
  const ordered = [...daily].sort((a, b) => (a.date < b.date ? 1 : -1))
  if (ordered.length === 0) return 0

  const oneDayMs = 24 * 60 * 60 * 1000
  let streak = 0
  let expected = ordered[0].date
  for (const entry of ordered) {
    if (entry.date !== expected) break
    if (entry.total_mm >= thresholdMm) break
    streak += 1
    expected = new Date(new Date(expected).getTime() - oneDayMs).toISOString().slice(0, 10)
  }
  return streak
}

/** Growing Degree Days for a single day: heat accumulated above a base
 * temperature below which the crop doesn't develop. Generic base (not
 * crop-specific), same threshold philosophy as the frost/dry-spell logic
 * above — a simple, honest signal rather than a crop model. */
export function growingDegreeDays(temperatureMeanC: number, baseTempC: number): number {
  return Math.max(0, temperatureMeanC - baseTempC)
}

/** Water balance for a day: rain in minus reference evapotranspiration out
 * (mm). Positive = net water gain, negative = net water deficit. */
export function waterBalanceMm(rainMm: number, et0Mm: number): number {
  return rainMm - et0Mm
}

export type DiseaseRisk = 'low' | 'high' | 'unknown'

/** Simplified daily proxy for fungal disease pressure: high humidity in a
 * mild temperature band favors fungal growth. A real model needs
 * consecutive-hours-above-threshold tracking, which the daily-granularity
 * forecast doesn't have — this is an approximation, not a diagnosis. */
export function classifyDiseaseRisk(
  humidityMeanPercent: number | null,
  temperatureMeanC: number | null,
  { humidityThresholdPercent, minTempC, maxTempC }: DiseaseRiskThresholds,
): DiseaseRisk {
  if (humidityMeanPercent == null || temperatureMeanC == null) return 'unknown'
  const humid = humidityMeanPercent >= humidityThresholdPercent
  const mildTemp = temperatureMeanC >= minTempC && temperatureMeanC <= maxTempC
  return humid && mildTemp ? 'high' : 'low'
}

export interface DiseaseRiskThresholds {
  humidityThresholdPercent: number
  minTempC: number
  maxTempC: number
}

export type VpdLevel = 'low' | 'ideal' | 'high' | 'unknown'

/** Vapor Pressure Deficit (kPa) — Tetens/FAO-56 saturation vapor pressure
 * formula. Low VPD (<0.4 kPa) means reduced transpiration/nutrient uptake;
 * high (>1.6 kPa) means plant stress from excessive water loss. */
export function vaporPressureDeficitKpa(
  temperatureMeanC: number,
  humidityMeanPercent: number,
): number {
  const svp = 0.6108 * Math.exp((17.27 * temperatureMeanC) / (temperatureMeanC + 237.3))
  return svp * (1 - humidityMeanPercent / 100)
}

export function classifyVpd(vpdKpa: number): VpdLevel {
  if (vpdKpa < 0.4) return 'low'
  if (vpdKpa <= 1.6) return 'ideal'
  return 'high'
}

export type NdviLevel = 'bare' | 'stressed' | 'moderate' | 'vigorous' | 'unknown'

/** Standard NDVI vegetation-vigor bands (FASE 29, ADR-0053) — same
 * deterministic-bucket spirit as `classifyCape`/`classifyVpd`, not a
 * per-crop model. `null` (no reading yet, or the location isn't a talhão)
 * is always 'unknown', never guessed at. */
export function classifyNdvi(ndviMean: number | null): NdviLevel {
  if (ndviMean == null) return 'unknown'
  if (ndviMean < 0.2) return 'bare'
  if (ndviMean < 0.4) return 'stressed'
  if (ndviMean < 0.6) return 'moderate'
  return 'vigorous'
}

export const NDVI_LABEL: Record<NdviLevel, string> = {
  bare: 'solo exposto/sem vegetação',
  stressed: 'vegetação esparsa ou em estresse',
  moderate: 'vegetação moderada',
  vigorous: 'vegetação vigorosa',
  unknown: 'sem leitura ainda',
}

export type Trafficability = 'trafficable' | 'not_trafficable' | 'unknown'

/** Whether the soil is dry enough for machinery/harvest: a real dry streak
 * behind, and no significant rain forecast ahead. `null`/missing forecast
 * rain is treated as "can't confirm dry ahead" — never assumed favorable
 * from missing data. */
export function evaluateTrafficability(
  daily: DailyRainfall[],
  upcoming: ForecastPoint[],
  {
    requiredDryDays,
    rainThresholdMm,
    lookaheadDays,
  }: { requiredDryDays: number; rainThresholdMm: number; lookaheadDays: number },
): Trafficability {
  const streak = dryStreakDays(daily, rainThresholdMm)
  if (streak < requiredDryDays) return 'not_trafficable'

  const ahead = upcoming.slice(0, lookaheadDays)
  if (ahead.length === 0) return 'unknown'
  const rainKnown = ahead.some((p) => p.precipitation_mm != null)
  if (!rainKnown) return 'unknown'
  const rainComing = ahead.some((p) => (p.precipitation_mm ?? 0) >= rainThresholdMm)
  return rainComing ? 'not_trafficable' : 'trafficable'
}
