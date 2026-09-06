import type { SatelliteImageMeta, StormCell } from './types'

export interface SatelliteTimelineStep {
  image: SatelliteImageMeta
  offsetMinutes: number
  estimated: boolean
}

const FUTURE_STEP_MINUTES = 10
const FUTURE_HORIZON_MINUTES = 60
const OBSERVATION_MATCH_MINUTES = 8

export function buildSatelliteTimeline(
  frames: SatelliteImageMeta[],
  hasStormProjection: boolean,
): SatelliteTimelineStep[] {
  if (frames.length === 0) return []
  const ordered = [...frames].sort(
    (a, b) => new Date(a.captured_at).getTime() - new Date(b.captured_at).getTime(),
  )
  const latest = ordered[ordered.length - 1]
  const latestMs = new Date(latest.captured_at).getTime()
  const observed = ordered
    .filter((frame, index) => index === 0 || frame.id !== ordered[index - 1].id)
    .map((image) => ({
      image,
      offsetMinutes: Math.round((new Date(image.captured_at).getTime() - latestMs) / 60_000),
      estimated: false,
    }))
    .filter((step) => step.offsetMinutes >= -60)
  if (!hasStormProjection) return observed
  return [
    ...observed,
    ...Array.from({ length: FUTURE_HORIZON_MINUTES / FUTURE_STEP_MINUTES }, (_, index) => ({
      image: latest,
      offsetMinutes: (index + 1) * FUTURE_STEP_MINUTES,
      estimated: true,
    })),
  ]
}

function withoutProjection(storm: StormCell): StormCell {
  return {
    ...storm,
    projected_latitude_1h: null,
    projected_longitude_1h: null,
  }
}

export function stormsForTimelineStep(
  storms: StormCell[],
  step: SatelliteTimelineStep,
): StormCell[] {
  if (step.estimated) {
    const fraction = Math.min(1, Math.max(0, step.offsetMinutes / FUTURE_HORIZON_MINUTES))
    return storms.flatMap((storm) => {
      if (storm.projected_latitude_1h == null || storm.projected_longitude_1h == null) return []
      return [
        withoutProjection({
          ...storm,
          latitude:
            storm.latitude + (storm.projected_latitude_1h - storm.latitude) * fraction,
          longitude:
            storm.longitude + (storm.projected_longitude_1h - storm.longitude) * fraction,
        }),
      ]
    })
  }
  if (step.offsetMinutes === 0) return storms
  const frameMs = new Date(step.image.captured_at).getTime()
  return storms
    .filter(
      (storm) =>
        Math.abs(new Date(storm.detected_at).getTime() - frameMs) <=
        OBSERVATION_MATCH_MINUTES * 60_000,
    )
    .map(withoutProjection)
}
