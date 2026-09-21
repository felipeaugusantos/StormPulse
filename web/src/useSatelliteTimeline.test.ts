import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { useSatelliteTimeline } from './useSatelliteTimeline'
import type { SatelliteImageMeta } from './types'

function frame(id: string, capturedAt: string): SatelliteImageMeta {
  return { id, captured_at: capturedAt, bbox: [-74, -34, -34, 6], band: 'B13', width: 10, height: 10 }
}

const FRAMES = [
  frame('a', '2026-09-05T11:50:00Z'),
  frame('b', '2026-09-05T12:00:00Z'),
]

describe('useSatelliteTimeline (Fase 8, ADR-0091)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  test('starts live (no selected index, no active step)', () => {
    const { result } = renderHook(() => useSatelliteTimeline(FRAMES, false))
    expect(result.current.index).toBeNull()
    expect(result.current.activeStep).toBeNull()
  })

  test('toggle enters playback from the first step and advances on an interval', () => {
    const { result } = renderHook(() => useSatelliteTimeline(FRAMES, false))
    act(() => result.current.toggle())
    expect(result.current.playing).toBe(true)
    expect(result.current.index).toBe(0)

    act(() => vi.advanceTimersByTime(900))
    expect(result.current.index).toBe(1)
  })

  test('stops playing and clamps at the last step instead of looping', () => {
    const { result } = renderHook(() => useSatelliteTimeline(FRAMES, false))
    act(() => result.current.toggle())
    act(() => vi.advanceTimersByTime(900))
    act(() => vi.advanceTimersByTime(900))
    expect(result.current.playing).toBe(false)
    expect(result.current.index).toBe(1)
  })

  test('a single frame opens it on toggle instead of staying disabled', () => {
    const { result } = renderHook(() => useSatelliteTimeline([FRAMES[0]], false))
    act(() => result.current.toggle())
    expect(result.current.playing).toBe(false)
    expect(result.current.index).toBe(0)
  })

  test('selectIndex stops playback and jumps straight to that step', () => {
    const { result } = renderHook(() => useSatelliteTimeline(FRAMES, false))
    act(() => result.current.toggle())
    act(() => result.current.selectIndex(1))
    expect(result.current.playing).toBe(false)
    expect(result.current.index).toBe(1)
    expect(result.current.activeStep?.image.id).toBe('b')
  })

  test('goLive clears the selection back to null', () => {
    const { result } = renderHook(() => useSatelliteTimeline(FRAMES, false))
    act(() => result.current.selectIndex(0))
    act(() => result.current.goLive())
    expect(result.current.index).toBeNull()
    expect(result.current.activeStep).toBeNull()
  })
})
