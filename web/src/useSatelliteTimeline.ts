import { useEffect, useMemo, useState } from 'react'
import { buildSatelliteTimeline, type SatelliteTimelineStep } from './stormTimeline'
import type { SatelliteImageMeta } from './types'

const AUTOPLAY_STEP_MS = 900

export interface SatelliteTimeline {
  steps: SatelliteTimelineStep[]
  /** `null` means "live" (the most recent real frame), not "no step". */
  index: number | null
  playing: boolean
  activeStep: SatelliteTimelineStep | null
  /** Index of the most recent *observed* (non-estimated) step — where the
   * slider sits while live, since there's no dedicated "now" step. */
  currentIndex: number
  toggle: () => void
  selectIndex: (index: number) => void
  goLive: () => void
}

/** Shared by `Dashboard` and `VisitorView` — same play/scrub-through-frames
 * behavior (Fase 8, ADR-0091) either way, just fed a different `frames`
 * source (authenticated vs. public satellite-image history). */
export function useSatelliteTimeline(
  frames: SatelliteImageMeta[],
  hasStormProjection: boolean,
): SatelliteTimeline {
  const [index, setIndex] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)

  const steps = useMemo(
    () => buildSatelliteTimeline(frames, hasStormProjection),
    [frames, hasStormProjection],
  )
  const activeStep = index == null ? null : (steps[index] ?? null)
  const currentIndex = steps.reduce(
    (latestIndex, step, stepIndex) => (step.estimated ? latestIndex : stepIndex),
    0,
  )

  useEffect(() => {
    if (!playing || steps.length < 2) return
    const timer = window.setInterval(() => {
      setIndex((current) => {
        const next = current == null ? 0 : current + 1
        if (next >= steps.length) {
          setPlaying(false)
          return steps.length - 1
        }
        return next
      })
    }, AUTOPLAY_STEP_MS)
    return () => window.clearInterval(timer)
  }, [playing, steps.length])

  useEffect(() => {
    if (index != null && index >= steps.length) {
      setIndex(null)
      setPlaying(false)
    }
  }, [index, steps.length])

  function toggle() {
    if (playing) {
      setPlaying(false)
      return
    }
    if (steps.length === 0) return
    if (steps.length === 1) {
      // A fresh deployment may only have the first observed frame. Let the
      // operator open it instead of presenting a mysteriously disabled play
      // control; animation starts naturally once another real/projection
      // step becomes available. No duplicate frame is invented here.
      setIndex(0)
      return
    }
    if (index == null || index >= steps.length - 1) setIndex(0)
    setPlaying(true)
  }

  function selectIndex(nextIndex: number) {
    setPlaying(false)
    setIndex(nextIndex)
  }

  function goLive() {
    setPlaying(false)
    setIndex(null)
  }

  return { steps, index, playing, activeStep, currentIndex, toggle, selectIndex, goLive }
}
