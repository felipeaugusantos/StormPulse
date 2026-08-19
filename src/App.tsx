import { useEffect, useMemo } from 'react'
import type { GeoResult } from './api/openMeteo'
import { useWeather } from './hooks/useWeather'
import { assessStorm } from './lib/storm'
import { weatherInfo } from './lib/weatherCodes'
import { relativeTime } from './lib/format'
import { SearchBar } from './components/SearchBar'
import { StormAlert } from './components/StormAlert'
import { CurrentConditions } from './components/CurrentConditions'
import { HourlyForecast } from './components/HourlyForecast'
import { DailyForecast } from './components/DailyForecast'

const DEFAULT_PLACE: GeoResult = {
  id: 3448439,
  name: 'São Paulo',
  latitude: -23.5475,
  longitude: -46.6361,
  country: 'Brasil',
  countryCode: 'BR',
  admin1: 'São Paulo',
  timezone: 'auto',
}

export default function App() {
  const { data, loading, error, load, refresh } = useWeather()

  // Load a default city on first mount.
  useEffect(() => {
    load(DEFAULT_PLACE)
  }, [load])

  const assessment = useMemo(() => (data ? assessStorm(data) : null), [data])

  const theme = data ? weatherInfo(data.current.weatherCode).theme : 'clear'
  const night = data ? !data.current.isDay : false

  return (
    <div className={`app theme-${theme} ${night ? 'night' : ''}`}>
      <div className="bg-orbs" aria-hidden>
        <span className="orb orb-a" />
        <span className="orb orb-b" />
      </div>

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>⚡</span>
          <span className="brand-name">Storm<strong>Pulse</strong></span>
        </div>
        <SearchBar onSelect={load} />
      </header>

      <main className="content">
        {loading && !data && (
          <div className="status-card">Carregando previsão…</div>
        )}

        {error && (
          <div className="status-card error">
            <p>⚠️ {error}</p>
            <button className="btn" onClick={refresh}>
              Tentar novamente
            </button>
          </div>
        )}

        {data && assessment && (
          <>
            <StormAlert assessment={assessment} />
            <CurrentConditions place={data.place} current={data.current} />
            <HourlyForecast hourly={data.hourly} />
            <DailyForecast daily={data.daily} />

            <footer className="footer">
              <span>
                Atualizado {relativeTime(data.fetchedAt)}
                {loading && ' · atualizando…'}
              </span>
              <button className="btn ghost" onClick={refresh} disabled={loading}>
                ↻ Atualizar
              </button>
              <span className="credit">
                Dados por{' '}
                <a href="https://open-meteo.com" target="_blank" rel="noreferrer">
                  Open-Meteo
                </a>
              </span>
            </footer>
          </>
        )}
      </main>
    </div>
  )
}
