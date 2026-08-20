import { useEffect, useState } from 'react'
import { api } from '../api'
import type { CurrentConditions, ForecastPoint, LocationItem, SprayWindow } from '../types'

// Mirrors AGRO_FROST_THRESHOLD_C default — see Dashboard.tsx's own copy of
// this same constant and ADR-0014.
const FROST_THRESHOLD_C = 3
const DAYS_TO_SHOW = 5

interface Props {
  location: LocationItem | null
}

export function LocationWeatherCard({ location }: Props) {
  const [current, setCurrent] = useState<CurrentConditions | null>(null)
  const [forecast, setForecast] = useState<ForecastPoint[] | null>(null)
  const [sprayWindow, setSprayWindow] = useState<SprayWindow | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!location) {
      setCurrent(null)
      setForecast(null)
      setSprayWindow(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      const [currentRes, forecastRes, sprayRes] = await Promise.all([
        api.currentConditions(location!.id).catch(() => null),
        api.forecast(location!.id).catch(() => null),
        api.sprayWindow(location!.id).catch(() => null),
      ])
      if (cancelled) return
      setCurrent(currentRes)
      setForecast(forecastRes?.points ?? null)
      setSprayWindow(sprayRes)
      setLoading(false)
      if (currentRes == null && forecastRes == null) {
        setError('Dados indisponíveis para este local no momento')
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [location])

  if (!location) {
    return (
      <section className="panel">
        <h2>🌡️ Clima do local</h2>
        <p className="empty">Selecione ou adicione um local para ver o clima.</p>
      </section>
    )
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const upcoming = (forecast ?? [])
    .filter((p) => new Date(p.time) >= today)
    .slice(0, DAYS_TO_SHOW)

  const frostRisk = upcoming.some(
    (p) => p.temperature_min_c != null && p.temperature_min_c <= FROST_THRESHOLD_C,
  )

  return (
    <section className="panel">
      <h2>🌡️ {location.name}</h2>
      {loading && !current && <p className="panel-hint">carregando…</p>}
      {error && <p className="error">⚠️ {error}</p>}

      {current && (
        <div className="weather-current">
          <span className="weather-current-temp">
            {current.temperature_c != null ? `${current.temperature_c.toFixed(0)}°C` : '—'}
          </span>
          <span className="weather-current-source">
            {current.provenance.source_name}
            {current.provenance.is_mock && <span className="mock-tag">MOCK</span>}
          </span>
        </div>
      )}

      {upcoming.length > 0 && (
        <div className="forecast-strip">
          {upcoming.map((p, i) => (
            <div className="forecast-strip-day" key={i}>
              <div className="sub">
                {new Date(p.time).toLocaleDateString('pt-BR', { weekday: 'short' })}
              </div>
              <div>{p.temperature_c != null ? `${p.temperature_c.toFixed(0)}°` : '—'}</div>
              <div className="sub">
                {p.temperature_min_c != null ? `${p.temperature_min_c.toFixed(0)}°` : '—'}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="agro-section">
        {frostRisk && (
          <div className="agro-row warn">
            ❄️ Risco de geada nos próximos dias (mínima ≤ {FROST_THRESHOLD_C}°C)
          </div>
        )}
        {sprayWindow && (
          <div className={`agro-row ${sprayWindow.safe === false ? 'warn' : ''}`}>
            🌬️{' '}
            {sprayWindow.wind_kmh != null ? `vento ${sprayWindow.wind_kmh.toFixed(0)} km/h` : 'vento indisponível'}
            {sprayWindow.wind_gusts_kmh != null
              ? ` (rajada ${sprayWindow.wind_gusts_kmh.toFixed(0)} km/h)`
              : ''}{' '}
            —{' '}
            {sprayWindow.safe == null
              ? 'não avaliável'
              : sprayWindow.safe
                ? 'janela segura pra pulverizar'
                : 'condições desfavoráveis'}
          </div>
        )}
      </div>
    </section>
  )
}
