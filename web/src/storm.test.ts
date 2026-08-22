import { describe, expect, test } from 'vitest'
import { bearingDeg, classifyCape, estimateStormEta, haversineDistanceKm } from './storm'

describe('classifyCape', () => {
  test('matches REDEMET 4-tier classification', () => {
    expect(classifyCape(500)).toBe('weak')
    expect(classifyCape(1500)).toBe('moderate')
    expect(classifyCape(3000)).toBe('strong')
    expect(classifyCape(5000)).toBe('extreme')
  })

  test('boundary values fall into the higher tier', () => {
    expect(classifyCape(1000)).toBe('moderate')
    expect(classifyCape(2500)).toBe('strong')
    expect(classifyCape(4000)).toBe('extreme')
  })
})

describe('haversineDistanceKm', () => {
  test('is zero for the same point', () => {
    expect(haversineDistanceKm(-23.55, -46.63, -23.55, -46.63)).toBeCloseTo(0)
  })

  test('matches a known distance (São Paulo to Rio, ~360km)', () => {
    const km = haversineDistanceKm(-23.5505, -46.6333, -22.9068, -43.1729)
    expect(km).toBeGreaterThan(340)
    expect(km).toBeLessThan(380)
  })
})

describe('bearingDeg', () => {
  test('due north is 0 degrees', () => {
    expect(bearingDeg(0, 0, 1, 0)).toBeCloseTo(0, 0)
  })

  test('due east is 90 degrees', () => {
    expect(bearingDeg(0, 0, 0, 1)).toBeCloseTo(90, 0)
  })
})

describe('estimateStormEta', () => {
  test('returns null when the cell has no speed/direction data', () => {
    expect(estimateStormEta(-23.5, -46.6, null, null, -23.5, -46.6)).toBeNull()
    expect(estimateStormEta(-23.5, -46.6, 0, 90, -23.5, -46.6)).toBeNull()
  })

  test('returns null when the cell is heading away from the target', () => {
    // Target is due east; cell heads due west (180° off) — nowhere near it.
    const result = estimateStormEta(-23.5, -46.6, 30, 270, -23.5, -46.0)
    expect(result).toBeNull()
  })

  test('estimates distance and ETA when heading toward the target', () => {
    // Target is due east of the cell; cell heads due east at 30 km/h.
    const result = estimateStormEta(-23.5, -46.6, 30, 90, -23.5, -46.1)
    expect(result).not.toBeNull()
    expect(result!.distanceKm).toBeGreaterThan(0)
    expect(result!.etaMinutes).toBeGreaterThan(0)
    // distance/speed*60 must hold exactly (pure arithmetic, no noise).
    expect(result!.etaMinutes).toBeCloseTo((result!.distanceKm / 30) * 60, 5)
  })
})
