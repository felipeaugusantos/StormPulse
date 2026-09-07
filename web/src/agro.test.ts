import { describe, expect, test } from 'vitest'
import {
  classifyFrostDays,
  classifyNdvi,
  dryStreakDays,
  formatFrostDays,
  formatFrostDaysAhead,
  formatZarcWindowAhead,
} from './agro'
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

describe('classifyNdvi', () => {
  test('buckets by the standard vegetation-vigor bands', () => {
    expect(classifyNdvi(0.1)).toBe('bare')
    expect(classifyNdvi(0.3)).toBe('stressed')
    expect(classifyNdvi(0.5)).toBe('moderate')
    expect(classifyNdvi(0.8)).toBe('vigorous')
  })

  test('boundary values fall into the higher (more vigorous) bucket', () => {
    expect(classifyNdvi(0.2)).toBe('stressed')
    expect(classifyNdvi(0.4)).toBe('moderate')
    expect(classifyNdvi(0.6)).toBe('vigorous')
  })

  test('null is always unknown, never guessed', () => {
    expect(classifyNdvi(null)).toBe('unknown')
  })
})

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

describe('formatFrostDaysAhead (Fase 4, ADR-0088)', () => {
  test('null for an empty list — no frost day to point at', () => {
    expect(formatFrostDaysAhead([])).toBeNull()
  })

  test('picks the earliest day when several are given, out of order', () => {
    const now = new Date('2026-08-01T00:00:00Z')
    const formatted = formatFrostDaysAhead(
      [point('2026-08-03T00:00:00Z', 1), point('2026-08-02T00:00:00Z', 0)],
      now,
    )
    expect(formatted).toBe('geada em 1 dia')
  })
})

describe('formatZarcWindowAhead (Fase 4, ADR-0088)', () => {
  test('null when every decêndio is 0 — no recommended window at all', () => {
    expect(formatZarcWindowAhead(new Array(36).fill(0))).toBeNull()
  })

  test('reports the soonest recommended decêndio ahead of now', () => {
    // decêndio 0 = Jan 1-10 — from Jan 5th, that's "em ~5 dias" until Jan 10
    // is irrelevant; the window STARTS Jan 1, already passed this year, so
    // the next occurrence is decêndio 0 next year unless a later one in the
    // current year is also recommended.
    const decendios = new Array(36).fill(0)
    decendios[5] = 20 // decêndio 5 = Feb 21 (month 1, period 2 -> day 21)
    const now = new Date(2026, 0, 1) // Jan 1, 2026 (local time)
    const formatted = formatZarcWindowAhead(decendios, now)
    expect(formatted).toMatch(/^janela recomendada em/)
  })

  test('wraps to next year when the only recommended decêndio already passed', () => {
    const decendios = new Array(36).fill(0)
    decendios[0] = 20 // decêndio 0 = Jan 1
    const now = new Date(2026, 5, 15) // June 15, well past Jan 1
    const formatted = formatZarcWindowAhead(decendios, now)
    // ~200 days until next Jan 1 — must still resolve, never null/negative.
    expect(formatted).toMatch(/^janela recomendada em \d+ dias$/)
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
