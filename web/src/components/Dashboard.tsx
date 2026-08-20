import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, clearToken, publicApi, readiness } from '../api'
import type {
  AlertItem,
  ConvectiveWatch,
  ForecastPoint,
  LocationItem,
  Me,
  ReadyStatus,
  SatelliteImageMeta,
  SprayWindow,
  StormCell,
} from '../types'
import { timeAgo } from '../format'
import { SatelliteWatchRow } from './SatelliteWatchRow'
import { StormMap, type StormMapHandle } from './StormMap'

interface Props {
  onLogout: () => void
}

const REFRESH_MS = 30_000

export function Dashboard({ onLogout }: Props) {
  const mapRef = useRef<StormMapHandle>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [storms, setStorms] = useState<StormCell[]>([])
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [satelliteWatches, setSatelliteWatches] = useState<ConvectiveWatch[]>([])
  const [satelliteImage, setSatelliteImage] = useState<SatelliteImageMeta | null>(null)
  const [showSatelliteImage, setShowSatelliteImage] = useState(true)
  const [ready, setReady] = useState<ReadyStatus | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [meRes, stormsRes, locsRes, alertsRes, satelliteRes, satelliteImageRes] =
        await Promise.all([
          api.me(),
          api.storms(),
          api.locations(),
          api.alerts(),
          api.satelliteWatches(),
          publicApi.satelliteImage(),
        ])
      setMe(meRes)
      setStorms(stormsRes)
      setLocations(locsRes)
      setAlerts(alertsRes)
      setSatelliteWatches(satelliteRes)
      setSatelliteImage(satelliteImageRes)
      setUpdatedAt(new Date())
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearToken()
        onLogout()
        return
      }
      setError(err instanceof Error ? err.message : 'Erro ao carregar')
    }
    try {
      setReady(await readiness())
    } catch {
      setReady(null)
    }
  }, [onLogout])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  const mock = storms.some((s) => s.is_mock)

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong> Admin
          </span>
        </div>
        {mock && <span className="mock-tag">DADOS MOCK</span>}
        <div className="spacer" />
        <div className="status-pills">
          <span className="pill">
            <span className={`dot ${ready?.checks.database === 'ok' ? 'ok' : 'bad'}`} />
            Postgres
          </span>
          <span className="pill">
            <span className={`dot ${ready?.checks.redis === 'ok' ? 'ok' : 'bad'}`} />
            Redis
          </span>
          <span className="pill">{me?.email ?? '—'}</span>
        </div>
        <button className="btn ghost" onClick={onLogout}>
          Sair
        </button>
      </header>

      <div className="layout">
        <div className="map-card">
          <StormMap
            ref={mapRef}
            storms={storms}
            locations={locations}
            satelliteWatches={satelliteWatches}
            satelliteImage={showSatelliteImage ? satelliteImage : null}
          />
          <div className="map-legend">
            <span className="legend-item">
              <span className="swatch" style={{ background: '#37d39b' }} /> fraca
            </span>
            <span className="legend-item">
              <span className="swatch" style={{ background: '#f2c14e' }} /> moderada
            </span>
            <span className="legend-item">
              <span className="swatch" style={{ background: '#f59e5b' }} /> forte
            </span>
            <span className="legend-item">
              <span className="swatch" style={{ background: '#ef6d6d' }} /> severa
            </span>
            <span className="legend-item">
              <span className="swatch" style={{ background: '#4cc2e6' }} /> local
            </span>
            <span className="legend-item">
              <span className="swatch" style={{ background: '#a78bfa' }} /> satélite
            </span>
            {satelliteImage && (
              <label className="legend-item satellite-image-toggle">
                <input
                  type="checkbox"
                  checked={showSatelliteImage}
                  onChange={(e) => setShowSatelliteImage(e.target.checked)}
                />
                imagem de satélite (IR) · {timeAgo(satelliteImage.captured_at)}
              </label>
            )}
          </div>
        </div>

        <div className="side">
          {error && <div className="panel error">⚠️ {error}</div>}
          <AlertsPanel alerts={alerts} />
          <StormsPanel storms={storms} />
          <SatelliteWatchesPanel
            watches={satelliteWatches}
            onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
          />
          <LocationsPanel locations={locations} />
          <AgroPanel
            locations={locations}
            onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
          />
          {updatedAt && (
            <div className="updated">
              Atualizado {updatedAt.toLocaleTimeString('pt-BR')} · atualização automática 30s
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function AlertsPanel({ alerts }: { alerts: AlertItem[] }) {
  return (
    <section className="panel">
      <h2>
        Alertas <span className="count">{alerts.length}</span>
      </h2>
      <div className="list">
        {alerts.length === 0 && <p className="empty">Nenhum alerta.</p>}
        {alerts.map((a) => (
          <div className="row" key={a.id}>
            <span className={`badge ${a.level}`}>{a.level}</span>
            <div className="grow">
              <div>{a.title}</div>
              <div className="sub">
                {a.event_type} · {new Date(a.created_at).toLocaleString('pt-BR')}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

const STORMS_PAGE_SIZE = 8

function StormsPanel({ storms }: { storms: StormCell[] }) {
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(storms.length / STORMS_PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const start = safePage * STORMS_PAGE_SIZE
  const pageItems = storms.slice(start, start + STORMS_PAGE_SIZE)

  return (
    <section className="panel">
      <h2>
        Células detectadas <span className="count">{storms.length}</span>
      </h2>
      <div className="list">
        {storms.length === 0 && (
          <p className="empty">Nenhuma célula. Rode o worker (pipeline) para materializar dados.</p>
        )}
        {pageItems.map((s) => (
          <div className="row" key={s.id}>
            <span className="badge sev">{s.severity}</span>
            <div className="grow">
              <div>
                {s.latitude.toFixed(2)}, {s.longitude.toFixed(2)}
              </div>
              <div className="sub">
                {s.max_reflectivity ? `${s.max_reflectivity.toFixed(0)} dBZ · ` : ''}
                {new Date(s.detected_at).toLocaleTimeString('pt-BR')}
              </div>
            </div>
            {s.is_mock && <span className="mock-tag">MOCK</span>}
          </div>
        ))}
      </div>
      {storms.length > STORMS_PAGE_SIZE && (
        <div className="pager">
          <button
            className="btn ghost small"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
          >
            ‹ Anterior
          </button>
          <span className="sub">
            {start + 1}–{Math.min(start + STORMS_PAGE_SIZE, storms.length)} de {storms.length}
          </span>
          <button
            className="btn ghost small"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={safePage >= pageCount - 1}
          >
            Próxima ›
          </button>
        </div>
      )}
    </section>
  )
}

function SatelliteWatchesPanel({
  watches,
  onSelect,
}: {
  watches: ConvectiveWatch[]
  onSelect: (latitude: number, longitude: number) => void
}) {
  return (
    <section className="panel">
      <h2>
        Observações via satélite <span className="count">{watches.length}</span>
      </h2>
      <p className="panel-hint">
        Nuvens esfriando no topo, vistas pelo satélite — sinal de que pode virar chuva, antes de
        aparecer como célula de tempestade. Clique numa observação para ver no mapa.
      </p>
      <div className="list">
        {watches.length === 0 && (
          <p className="empty">
            Nenhuma observação ativa (ou SATELLITE_ENABLED=false — ver README).
          </p>
        )}
        {watches.map((w) => (
          <SatelliteWatchRow key={w.id} watch={w} onSelect={onSelect} />
        ))}
      </div>
    </section>
  )
}

// Mirrors the backend default (AGRO_FROST_THRESHOLD_C) for the client-side
// derivation below — a generic agronomic reference, not crop-specific;
// see ADR-0014. Not fetched dynamically: same reasoning as other
// thresholds already baked into this dashboard.
const FROST_THRESHOLD_C = 3

function LocationsPanel({ locations }: { locations: LocationItem[] }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [forecast, setForecast] = useState<ForecastPoint[] | null>(null)
  const [forecastError, setForecastError] = useState<string | null>(null)

  async function toggle(id: string) {
    if (selected === id) {
      setSelected(null)
      setForecast(null)
      setForecastError(null)
      return
    }
    setSelected(id)
    setForecast(null)
    setForecastError(null)
    try {
      const data = await api.forecast(id)
      setForecast(data.points)
    } catch (err) {
      setForecastError(err instanceof ApiError ? err.message : 'Previsão indisponível')
    }
  }

  return (
    <section className="panel">
      <h2>
        Locais monitorados <span className="count">{locations.length}</span>
      </h2>
      <div className="list">
        {locations.length === 0 && <p className="empty">Nenhum local cadastrado.</p>}
        {locations.map((l) => (
          <div key={l.id}>
            <div
              className={`row clickable ${selected === l.id ? 'selected' : ''}`}
              onClick={() => toggle(l.id)}
            >
              <div className="grow">
                <div>{l.name}</div>
                <div className="sub">
                  {l.kind} · raio {l.radius_km} km
                </div>
              </div>
              <span className="count">{l.alert_preferences.filter((p) => p.enabled).length}⚑</span>
            </div>
            {selected === l.id && (
              <div className="forecast">
                {forecastError && <span className="sub">⚠️ {forecastError}</span>}
                {forecast &&
                  forecast.map((p, i) => (
                    <div className={`forecast-row ${i === 0 ? 'past' : ''}`} key={i}>
                      <span className="sub">
                        {new Date(p.time).toLocaleDateString('pt-BR', {
                          day: '2-digit',
                          month: '2-digit',
                        })}
                        {i === 0 ? ' (ontem)' : ''}
                      </span>
                      <span>{p.temperature_c != null ? `${p.temperature_c.toFixed(0)}°C` : '—'}</span>
                    </div>
                  ))}
                {forecast && forecast.length === 0 && (
                  <span className="sub">Sem pontos de previsão.</span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

interface AgroEntry {
  frostRisk: boolean
  sprayWindow: SprayWindow | null
  rainfallTotalMm: number | null
  rainfallDays: number
  error: string | null
}

function AgroPanel({
  locations,
  onSelect,
}: {
  locations: LocationItem[]
  onSelect: (latitude: number, longitude: number) => void
}) {
  const [entries, setEntries] = useState<Record<string, AgroEntry>>({})
  const activeIds = locations
    .filter((l) => l.is_active)
    .map((l) => l.id)
    .join(',')

  useEffect(() => {
    let cancelled = false
    const active = locations.filter((l) => l.is_active)

    async function load() {
      const results = await Promise.all(
        active.map(async (l): Promise<[string, AgroEntry]> => {
          try {
            const [forecast, sprayWindow, rainfall] = await Promise.all([
              api.forecast(l.id).catch(() => null),
              api.sprayWindow(l.id).catch(() => null),
              api.rainfall(l.id).catch(() => null),
            ])
            return [
              l.id,
              {
                frostRisk:
                  forecast?.points.some(
                    (p) => p.temperature_min_c != null && p.temperature_min_c <= FROST_THRESHOLD_C,
                  ) ?? false,
                sprayWindow,
                rainfallTotalMm: rainfall
                  ? rainfall.daily.reduce((sum, d) => sum + d.total_mm, 0)
                  : null,
                rainfallDays: rainfall?.daily.length ?? 0,
                error:
                  forecast == null && sprayWindow == null && rainfall == null
                    ? 'Dados agro indisponíveis no momento'
                    : null,
              },
            ]
          } catch {
            return [
              l.id,
              {
                frostRisk: false,
                sprayWindow: null,
                rainfallTotalMm: null,
                rainfallDays: 0,
                error: 'Dados agro indisponíveis no momento',
              },
            ]
          }
        }),
      )
      if (!cancelled) setEntries(Object.fromEntries(results))
    }

    load()
    const t = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIds])

  const activeLocations = locations.filter((l) => l.is_active)

  return (
    <section className="panel">
      <h2>
        🌾 Agro <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">
        Geada (previsão), pulverização (vento + chuva prevista quando disponível) e chuva
        acumulada, por local monitorado.
      </p>
      <div className="list">
        {activeLocations.length === 0 && (
          <p className="empty">Nenhum local monitorado ativo.</p>
        )}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          return (
            <div
              className="row clickable"
              key={l.id}
              onClick={() => onSelect(l.latitude, l.longitude)}
              role="button"
              tabIndex={0}
            >
              <div className="grow">
                <div>{l.name}</div>
                {!entry && <div className="sub">carregando…</div>}
                {entry?.error && <div className="sub">⚠️ {entry.error}</div>}
                {entry && !entry.error && (
                  <div className="agro-section">
                    {entry.frostRisk && (
                      <div className="agro-row warn">
                        ❄️ Risco de geada nos próximos dias (mínima ≤ {FROST_THRESHOLD_C}°C)
                      </div>
                    )}
                    {entry.sprayWindow && (
                      <div className={`agro-row ${entry.sprayWindow.safe === false ? 'warn' : ''}`}>
                        🌬️{' '}
                        {entry.sprayWindow.wind_kmh != null
                          ? `vento ${entry.sprayWindow.wind_kmh.toFixed(0)} km/h`
                          : 'vento indisponível'}
                        {entry.sprayWindow.wind_gusts_kmh != null
                          ? ` (rajada ${entry.sprayWindow.wind_gusts_kmh.toFixed(0)} km/h)`
                          : ''}{' '}
                        —{' '}
                        {entry.sprayWindow.safe == null
                          ? 'não avaliável'
                          : entry.sprayWindow.safe
                            ? 'janela segura pra pulverizar'
                            : entry.sprayWindow.rain_probability_percent != null &&
                                entry.sprayWindow.rain_probability_percent >=
                                  entry.sprayWindow.max_rain_probability_percent
                              ? `chuva provável (${entry.sprayWindow.rain_probability_percent}%)`
                              : `vento acima do limite de ${entry.sprayWindow.max_wind_kmh.toFixed(0)} km/h`}
                      </div>
                    )}
                    {entry.rainfallTotalMm != null && (
                      <div className="agro-row">
                        🌧️ {entry.rainfallTotalMm.toFixed(0)}mm acumulados ({entry.rainfallDays}{' '}
                        dias)
                      </div>
                    )}
                    {!entry.frostRisk && !entry.sprayWindow && entry.rainfallTotalMm == null && (
                      <div className="agro-row sub">Sem sinais no momento.</div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
