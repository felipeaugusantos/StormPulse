import { describe, expect, test } from 'vitest'
import { buildSatelliteTimeline, stormsForTimelineStep } from './stormTimeline'
import type { SatelliteImageMeta, StormCell } from './types'

function frame(id: string, capturedAt: string): SatelliteImageMeta {
  return { id, captured_at: capturedAt, bbox: [-74, -34, -34, 6], band: 'B13', width: 10, height: 10 }
}

const storm: StormCell = {
  id: 'storm-1',
  detected_at: '2026-09-05T12:00:00Z',
  latitude: -20,
  longitude: -50,
  severity: 'strong',
  max_reflectivity: 50,
  average_reflectivity: 40,
  area_km2: 100,
  is_mock: false,
  speed_kmh: 40,
  direction_deg: 90,
  projected_latitude_1h: -20,
  projected_longitude_1h: -49,
}

describe('satellite/storm timeline', () => {
  test('keeps the observed last hour and adds clearly estimated steps through +60 min', () => {
    const steps = buildSatelliteTimeline(
      [
        frame('old', '2026-09-05T10:50:00Z'),
        frame('past', '2026-09-05T11:10:00Z'),
        frame('now', '2026-09-05T12:00:00Z'),
      ],
      true,
    )
    expect(steps.map((step) => step.offsetMinutes)).toEqual([-50, 0, 10, 20, 30, 40, 50, 60])
    expect(steps.filter((step) => step.estimated)).toHaveLength(6)
  })

  test('does not invent future steps without a measured storm trajectory', () => {
    const steps = buildSatelliteTimeline([frame('now', '2026-09-05T12:00:00Z')], false)
    expect(steps).toHaveLength(1)
    expect(steps[0].estimated).toBe(false)
  })

  test('interpolates only cells that have a real one-hour projection', () => {
    const step = buildSatelliteTimeline([frame('now', '2026-09-05T12:00:00Z')], true)[3]
    const projected = stormsForTimelineStep([storm], step)
    expect(projected[0].longitude).toBeCloseTo(-49.5)
    expect(projected[0].projected_longitude_1h).toBeNull()
  })
})
