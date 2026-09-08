import { timeAgo, timeUntil } from '../format'

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

describe('timeAgo (Fase 6, ADR-0090)', () => {
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
