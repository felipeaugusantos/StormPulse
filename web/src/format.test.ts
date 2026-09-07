import { describe, expect, test } from 'vitest'
import {
  alertEventLabel,
  cardinalDirection,
  convectiveIntensity,
  formatDecimalBR,
  formatForecastDateBR,
  isForecastDayCurrentOrFuture,
  isForecastDayToday,
  kelvinToCelsius,
  riskLevelLabel,
  timeAgo,
  timeUntil,
} from './format'

describe('formatDecimalBR', () => {
  test('uses Brazilian decimal punctuation', () => {
    expect(formatDecimalBR(9.7)).toBe('9,7')
  })
})

describe('daily forecast dates', () => {
  test('does not shift a UTC calendar day back to the previous day in Brasília', () => {
    expect(formatForecastDateBR('2026-09-06T00:00:00Z', { weekday: 'long' })).toBe('domingo')
  })

  test('keeps the current UTC-midnight forecast day in a Brazilian local-day filter', () => {
    const saturdayEvening = new Date('2026-09-05T22:00:00Z')
    expect(isForecastDayCurrentOrFuture('2026-09-05T00:00:00Z', saturdayEvening)).toBe(true)
    expect(isForecastDayToday('2026-09-05T00:00:00Z', saturdayEvening)).toBe(true)
    expect(isForecastDayCurrentOrFuture('2026-09-04T00:00:00Z', saturdayEvening)).toBe(false)
  })
})

describe('kelvinToCelsius', () => {
  test('converts freezing point', () => {
    expect(kelvinToCelsius(273.15)).toBeCloseTo(0)
  })
})

describe('convectiveIntensity', () => {
  test('classifies by cloud-top temperature buckets', () => {
    expect(convectiveIntensity(273.15 - 70).className).toBe('red') // -70C
    expect(convectiveIntensity(273.15 - 60).className).toBe('orange') // -60C
    expect(convectiveIntensity(273.15 - 50).className).toBe('yellow') // -50C
    expect(convectiveIntensity(273.15 - 10).className).toBe('green') // -10C
  })

  test('boundary values fall into the colder (more severe) bucket', () => {
    expect(convectiveIntensity(273.15 - 65).className).toBe('red')
    expect(convectiveIntensity(273.15 - 55).className).toBe('orange')
    expect(convectiveIntensity(273.15 - 45).className).toBe('yellow')
  })
})

describe('cardinalDirection', () => {
  test('maps degrees to the 8-point compass', () => {
    expect(cardinalDirection(0)).toBe('N')
    expect(cardinalDirection(90)).toBe('L')
    expect(cardinalDirection(180)).toBe('S')
    expect(cardinalDirection(270)).toBe('O')
  })

  test('wraps negative and >360 degrees correctly', () => {
    expect(cardinalDirection(-45)).toBe(cardinalDirection(315))
    expect(cardinalDirection(405)).toBe(cardinalDirection(45))
  })
})

describe('riskLevelLabel', () => {
  test('translates the internal color codes into plain-language severity', () => {
    expect(riskLevelLabel('green')).toBe('Baixo')
    expect(riskLevelLabel('yellow')).toBe('Moderado')
    expect(riskLevelLabel('orange')).toBe('Alto')
    expect(riskLevelLabel('red')).toBe('Severo')
  })

  test('falls back to the raw code for anything unmapped, never hides it', () => {
    expect(riskLevelLabel('purple')).toBe('purple')
  })
})

describe('alertEventLabel', () => {
  test('translates known alert event-type codes into plain language', () => {
    expect(alertEventLabel('dry_spell_warning')).toBe('Sequência sem chuva')
    expect(alertEventLabel('frost_warning')).toBe('Risco de geada')
    expect(alertEventLabel('storm_approaching')).toBe('Tempestade se aproximando')
  })

  test('falls back to the raw code for an unmapped event type', () => {
    expect(alertEventLabel('some_future_event')).toBe('some_future_event')
  })
})

describe('timeAgo', () => {
  test('reports "agora" for the current instant', () => {
    expect(timeAgo(new Date().toISOString())).toBe('agora')
  })

  test('reports minutes for a recent timestamp', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(timeAgo(fiveMinAgo)).toBe('há 5 min')
  })

  test('reports hours once past 60 minutes', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60_000).toISOString()
    expect(timeAgo(twoHoursAgo)).toBe('há 2 h')
  })
})

describe('timeUntil (Fase 4, ADR-0088)', () => {
  test('reports "a qualquer momento" for zero or negative minutes', () => {
    expect(timeUntil(0)).toBe('a qualquer momento')
    expect(timeUntil(-5)).toBe('a qualquer momento')
  })

  test('reports minutes under an hour', () => {
    expect(timeUntil(5)).toBe('em 5 min')
    expect(timeUntil(59)).toBe('em 59 min')
  })

  test('reports hours between one hour and one day', () => {
    expect(timeUntil(120)).toBe('em ~2 h')
    expect(timeUntil(60 * 23)).toBe('em ~23 h')
  })

  test('reports days from 24 hours onward, singular for exactly one day', () => {
    expect(timeUntil(60 * 24)).toBe('em 1 dia')
    expect(timeUntil(60 * 24 * 3)).toBe('em 3 dias')
  })
})
