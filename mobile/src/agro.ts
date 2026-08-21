/** Pure agro-signal helpers — ported verbatim from `web/src/agro.ts`
 * (FASE 26, ADR-0023): no DOM dependency, so the same logic applies as-is
 * to the mobile app. Mirrors the equivalent backend logic in
 * `backend/workers/agro_pipeline.py` (frost tiers) and reimplements
 * `dry_streak_days` client-side since only raw daily totals are exposed via
 * `/agro/rainfall`, not the computed streak itself (FASE 22, ADR-0018). */

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
      const day = new Date(p.time).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
      const temp = p.temperature_min_c != null ? `${p.temperature_min_c.toFixed(1)}°C` : '—'
      return `${day} (${temp})`
    })
    .join(', ')
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
