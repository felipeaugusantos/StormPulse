/** Pure agro-signal helpers shared by LocationWeatherCard and the Agro
 * panel — mirrors the equivalent backend logic in
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
