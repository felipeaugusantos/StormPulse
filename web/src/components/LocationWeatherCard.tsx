import { useEffect, useState } from 'react'
import { api } from '../api'
import { classifyFrostDays, evaluateTrafficability, formatFrostDays } from '../agro'
import type {
  CurrentConditions,
  DailyRainfall,
  ForecastPoint,
  LocationItem,
  SprayWindow,
} from '../types'

// Mirrors the backend's AGRO_FROST_THRESHOLD_C/AGRO_FROST_LIGHT_THRESHOLD_C
// defaults — see ADR-0014/ADR-0018.
const FROST_THRESHOLD_C = 3
const FROST_LIGHT_THRESHOLD_C = 6
const DAYS_TO_SHOW = 5
const TRAFFICABILITY_DRY_DAYS = 2
const TRAFFICABILITY_RAIN_THRESHOLD_MM = 1
const TRAFFICABILITY_LOOKAHEAD_DAYS = 2

interface Props {
  location: LocationItem | null
}

export function LocationWeatherCard({ location }: Props) {
  const [current, setCurrent] = useState<CurrentConditions | null>(null)
  const [forecast, setForecast] = useState<ForecastPoint[] | null>(null)
  const [sprayWindow, setSprayWindow] = useState<SprayWindow | null>(null)
  const [rainfall, setRainfall] = useState<DailyRainfall[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!location) {
      setCurrent(null)
      setForecast(null)
      setSprayWindow(null)
      setRainfall(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      const [currentRes, forecastRes, sprayRes, rainfallRes] = await Promise.all([
        api.currentConditions(location!.id).catch(() => null),
        api.forecast(location!.id).catch(() => null),
        api.sprayWindow(location!.id).catch(() => null),
        api.rainfall(location!.id).catch(() => null),
      ])
      if (cancelled) return
      setCurrent(currentRes)
      setForecast(forecastRes?.points ?? null)
      setSprayWindow(sprayRes)
      setRainfall(rainfallRes?.daily ?? null)
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

  const { severe: severeFrostDays, light: lightFrostDays } = classifyFrostDays(
    upcoming,
    FROST_THRESHOLD_C,
    FROST_LIGHT_THRESHOLD_C,
  )
  const trafficability = rainfall
    ? evaluateTrafficability(rainfall, upcoming, {
        requiredDryDays: TRAFFICABILITY_DRY_DAYS,
        rainThresholdMm: TRAFFICABILITY_RAIN_THRESHOLD_MM,
        lookaheadDays: TRAFFICABILITY_LOOKAHEAD_DAYS,
      })
    : null

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
        {severeFrostDays.length > 0 && (
          <div className="agro-row warn">
            ❄️ Geada forte prevista (≤{FROST_THRESHOLD_C}°C): {formatFrostDays(severeFrostDays)}
          </div>
        )}
        {lightFrostDays.length > 0 && (
          <div className="agro-row warn">
            🌡️ Risco leve de geada (≤{FROST_LIGHT_THRESHOLD_C}°C): {formatFrostDays(lightFrostDays)}
          </div>
        )}
        {sprayWindow && (
          <div className={`agro-row ${sprayWindow.safe === false ? 'warn' : ''}`}>
            🌬️{' '}
            {sprayWindow.wind_kmh != null
              ? `vento ${sprayWindow.wind_kmh.toFixed(0)} km/h`
              : 'vento indisponível'}
            {sprayWindow.wind_gusts_kmh != null
              ? ` (rajada ${sprayWindow.wind_gusts_kmh.toFixed(0)} km/h)`
              : ''}
            {sprayWindow.humidity_percent != null
              ? ` · umidade ${sprayWindow.humidity_percent.toFixed(0)}%`
              : ''}{' '}
            —{' '}
            {sprayWindow.safe == null
              ? 'não avaliável'
              : sprayWindow.safe
                ? 'janela segura pra pulverizar'
                : sprayWindow.inversion_risk
                  ? 'risco de inversão térmica (vento calmo + umidade alta) — deriva'
                  : 'condições desfavoráveis'}
          </div>
        )}
        {trafficability && trafficability !== 'unknown' && (
          <div className={`agro-row ${trafficability === 'not_trafficable' ? 'warn' : ''}`}>
            🚜{' '}
            {trafficability === 'trafficable'
              ? 'solo seco — condições favoráveis para manejo/colheita'
              : 'solo úmido ou chuva prevista — evitar manejo pesado/colheita'}
          </div>
        )}
      </div>
    </section>
  )
}
