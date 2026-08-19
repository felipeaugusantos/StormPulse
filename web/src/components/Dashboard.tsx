import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, clearToken, readiness } from '../api'
import type { AlertItem, LocationItem, Me, ReadyStatus, StormCell } from '../types'
import { StormMap } from './StormMap'

interface Props {
  onLogout: () => void
}

const REFRESH_MS = 30_000

export function Dashboard({ onLogout }: Props) {
  const [me, setMe] = useState<Me | null>(null)
  const [storms, setStorms] = useState<StormCell[]>([])
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [ready, setReady] = useState<ReadyStatus | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [meRes, stormsRes, locsRes, alertsRes] = await Promise.all([
        api.me(),
        api.storms(),
        api.locations(),
        api.alerts(),
      ])
      setMe(meRes)
      setStorms(stormsRes)
      setLocations(locsRes)
      setAlerts(alertsRes)
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
          <StormMap storms={storms} locations={locations} />
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
          </div>
        </div>

        <div className="side">
          {error && <div className="panel error">⚠️ {error}</div>}
          <AlertsPanel alerts={alerts} />
          <StormsPanel storms={storms} />
          <LocationsPanel locations={locations} />
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

function StormsPanel({ storms }: { storms: StormCell[] }) {
  return (
    <section className="panel">
      <h2>
        Células detectadas <span className="count">{storms.length}</span>
      </h2>
      <div className="list">
        {storms.length === 0 && (
          <p className="empty">Nenhuma célula. Rode o worker (pipeline) para materializar dados.</p>
        )}
        {storms.slice(0, 12).map((s) => (
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
    </section>
  )
}

function LocationsPanel({ locations }: { locations: LocationItem[] }) {
  return (
    <section className="panel">
      <h2>
        Locais monitorados <span className="count">{locations.length}</span>
      </h2>
      <div className="list">
        {locations.length === 0 && <p className="empty">Nenhum local cadastrado.</p>}
        {locations.map((l) => (
          <div className="row" key={l.id}>
            <div className="grow">
              <div>{l.name}</div>
              <div className="sub">
                {l.kind} · raio {l.radius_km} km
              </div>
            </div>
            <span className="count">{l.alert_preferences.filter((p) => p.enabled).length}⚑</span>
          </div>
        ))}
      </div>
    </section>
  )
}
