import { describe, expect, test } from 'vitest'
import { classifyFrostDays, dryStreakDays, formatFrostDays } from './agro'
import type { DailyRainfall, ForecastPoint } from './types'

function point(time: string, temperature_min_c: number | null): ForecastPoint {
  return {
    time,
    temperature_c: null,
    temperature_min_c,
    precipitation_probability: null,
    precipitation_mm: null,
    temperature_mean_c: null,
    humidity_mean_percent: null,
    humidity_max_percent: null,
    wind_gusts_max_kmh: null,
    evapotranspiration_mm: null,
    cape_max_jkg: null,
  }
}

describe('classifyFrostDays', () => {
  test('splits severe vs light by the two thresholds', () => {
    const points = [
      point('2026-08-01', 1.0), // severe (<=3)
      point('2026-08-02', 4.5), // light (>3, <=6)
      point('2026-08-03', 10.0), // neither
      point('2026-08-04', null), // no data, excluded from both
    ]
    const result = classifyFrostDays(points, 3.0, 6.0)
    expect(result.severe).toHaveLength(1)
    expect(result.severe[0].time).toBe('2026-08-01')
    expect(result.light).toHaveLength(1)
    expect(result.light[0].time).toBe('2026-08-02')
  })

  test('boundary temperature at the severe threshold counts as severe', () => {
    const result = classifyFrostDays([point('2026-08-01', 3.0)], 3.0, 6.0)
    expect(result.severe).toHaveLength(1)
    expect(result.light).toHaveLength(0)
  })
})

describe('formatFrostDays', () => {
  test('formats each point as "dd/mm (X.X°C)"', () => {
    const formatted = formatFrostDays([point('2026-08-01T00:00:00Z', 2.5)])
    expect(formatted).toContain('2.5°C')
  })

  test('shows an em-dash placeholder when temperature is missing', () => {
    const formatted = formatFrostDays([point('2026-08-01T00:00:00Z', null)])
    expect(formatted).toContain('—')
  })
})

describe('dryStreakDays', () => {
  function daily(date: string, total_mm: number): DailyRainfall {
    return { date, total_mm }
  }

  test('counts consecutive dry days from the most recent backward', () => {
    const days = [
      daily('2026-08-05', 0),
      daily('2026-08-04', 0.5),
      daily('2026-08-03', 0),
      daily('2026-08-02', 5.0), // rain here, but before the break below
      daily('2026-08-01', 0),
    ]
    // threshold 1mm: 08-05 (0) dry, 08-04 (0.5) dry, 08-03 (0) dry,
    // 08-02 (5.0) breaks the streak.
    expect(dryStreakDays(days, 1.0)).toBe(3)
  })

  test('stops at a gap in the data instead of assuming it was dry', () => {
    const days = [
      daily('2026-08-05', 0),
      // 08-04 missing — must not silently count as dry.
      daily('2026-08-03', 0),
    ]
    expect(dryStreakDays(days, 1.0)).toBe(1)
  })

  test('returns 0 for empty history', () => {
    expect(dryStreakDays([], 1.0)).toBe(0)
  })

  test('a day right at the threshold breaks the streak (not dry)', () => {
    const days = [daily('2026-08-05', 1.0)]
    expect(dryStreakDays(days, 1.0)).toBe(0)
  })
})
