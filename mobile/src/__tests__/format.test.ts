import { timeUntil } from '../format'

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
