import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchForecast, type Forecast, type GeoResult } from '../api/openMeteo'

interface State {
  data: Forecast | null
  loading: boolean
  error: string | null
}

const REFRESH_MS = 5 * 60 * 1000 // auto-refresh every 5 minutes

export function useWeather() {
  const [state, setState] = useState<State>({ data: null, loading: false, error: null })
  const placeRef = useRef<GeoResult | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async (place: GeoResult) => {
    placeRef.current = place
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fetchForecast(place)
      setState({ data, loading: false, error: null })
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : 'Erro desconhecido',
      }))
    }
  }, [])

  const refresh = useCallback(() => {
    if (placeRef.current) load(placeRef.current)
  }, [load])

  // Set up / tear down the auto-refresh interval once.
  useEffect(() => {
    timerRef.current = setInterval(() => {
      if (placeRef.current) refresh()
    }, REFRESH_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [refresh])

  return { ...state, load, refresh }
}
