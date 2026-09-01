import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, publicApi, readiness, resendVerification } from '../api'
import type {
  AlertItem,
  ConvectiveWatch,
  ForecastPoint,
  LightningStrike,
  LocationItem,
  Me,
  NdviReading,
  ReadyStatus,
  SatelliteImageMeta,
  SprayWindow,
  StormCell,
  ZarcWindow,
} from '../types'
import {
  classifyDiseaseRisk,
  classifyFrostDays,
  classifyNdvi,
  classifyVpd,
  evaluateTrafficability,
  formatFrostDays,
  growingDegreeDays,
  NDVI_LABEL,
  vaporPressureDeficitKpa,
  waterBalanceMm,
  type DiseaseRisk,
  type NdviLevel,
  type Trafficability,
  type VpdLevel,
} from '../agro'
import { classifyCape, estimateStormEta, type CapeLevel } from '../storm'
import { cropColor } from '../cropColors'
import { formatDateBR, formatTimeBR, riskLevelLabel, timeAgo } from '../format'
import { isPushSupported, subscribeToPush } from '../push'
import { AdminPanel } from './AdminPanel'
import { ApiKeysModal } from './ApiKeysModal'
import { LocationSearchCard } from './LocationSearchCard'
import { LocationWeatherCard } from './LocationWeatherCard'
import { SafetyDisclaimer } from './SafetyDisclaimer'
import { SatelliteWatchRow } from './SatelliteWatchRow'
import { StormMap, type PlotBoundary, type StormMapHandle } from './LazyStormMap'

interface Props {
  onLogout: () => void
}

const REFRESH_MS = 30_000

// Agro alert types (backend `AlertEventType.FROST_WARNING`/`DRY_SPELL_WARNING`)
// must never surface in the Tempestade tab — the two tabs are deliberately
// independent (module selection, FASE 30/32). The Agro tab already shows
// this same information live via FrostPanel/RainfallPanel, computed fresh
// rather than read from the persisted Alert row.
const AGRO_ALERT_EVENT_TYPES = new Set(['frost_warning', 'dry_spell_warning'])

export function Dashboard({ onLogout }: Props) {
  const mapRef = useRef<StormMapHandle>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [storms, setStorms] = useState<StormCell[]>([])
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [satelliteWatches, setSatelliteWatches] = useState<ConvectiveWatch[]>([])
  const [satelliteImage, setSatelliteImage] = useState<SatelliteImageMeta | null>(null)
  const [lightning, setLightning] = useState<LightningStrike[]>([])
  const [showSatelliteImage, setShowSatelliteImage] = useState(true)
  const [satelliteBasemap, setSatelliteBasemap] = useState(false)
  const [showLegend, setShowLegend] = useState(true)
  const [drawingActive, setDrawingActive] = useState(false)
  const [drawError, setDrawError] = useState<string | null>(null)
  const [pickingLocation, setPickingLocation] = useState(false)
  const pendingBoundaryCallbackRef = useRef<((boundaryGeojson: string) => void) | null>(null)
  const [ready, setReady] = useState<ReadyStatus | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'storm' | 'agro'>('storm')
  const [deletingAccount, setDeletingAccount] = useState(false)
  const [verificationSent, setVerificationSent] = useState<
    'sent' | 'already-verified' | 'error' | null
  >(null)
  const [pushStatus, setPushStatus] = useState<'idle' | 'subscribing' | 'on' | 'error'>('idle')
  const [pushError, setPushError] = useState<string | null>(null)
  const [showAdmin, setShowAdmin] = useState(false)
  const [showApiKeys, setShowApiKeys] = useState(false)

  const load = useCallback(async () => {
    try {
      const [meRes, stormsRes, locsRes, alertsRes, satelliteRes, satelliteImageRes, lightningRes] =
        await Promise.all([
          api.me(),
          api.storms(),
          api.locations(),
          api.alerts(),
          api.satelliteWatches(),
          publicApi.satelliteImage(),
          api.lightning(),
        ])
      setMe(meRes)
      setStorms(stormsRes)
      setLocations(locsRes)
      setAlerts(alertsRes)
      setSatelliteWatches(satelliteRes)
      setSatelliteImage(satelliteImageRes)
      setLightning(lightningRes)
      setUpdatedAt(new Date())
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // The refresh cookie itself is gone/expired (request() already
        // tried it once) — nothing left to do but end the session.
        // `onLogout` (App.tsx) already clears local state and calls the
        // backend; no need to duplicate that here.
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

  useEffect(() => {
    if (selectedLocationId != null && locations.some((l) => l.id === selectedLocationId)) return
    const firstActive = locations.find((l) => l.is_active) ?? locations[0]
    setSelectedLocationId(firstActive?.id ?? null)
  }, [locations, selectedLocationId])

  // Module selection (FASE 30) — if the current tab isn't one the tenant
  // actually has, switch to whichever one it does have. Both are always
  // true/false at registration (never both false — enforced server-side),
  // so exactly one of these branches applies when only one module is on.
  useEffect(() => {
    if (!me) return
    if (activeTab === 'agro' && !me.agro_module_enabled) setActiveTab('storm')
    if (activeTab === 'storm' && !me.storm_module_enabled) setActiveTab('agro')
  }, [me, activeTab])

  function handleLocationCreated(created: LocationItem) {
    setLocations((prev) => [...prev, created])
  }

  function handleLocationUpdated(updated: LocationItem) {
    setLocations((prev) => prev.map((l) => (l.id === updated.id ? updated : l)))
  }

  function handleLocationDeleted(id: string) {
    setLocations((prev) => prev.filter((l) => l.id !== id))
    setSelectedLocationId((prev) => (prev === id ? null : prev))
  }

  function handleStartDrawBoundary(onComplete: (boundaryGeojson: string) => void) {
    pendingBoundaryCallbackRef.current = onComplete
    setDrawError(null)
    setDrawingActive(true)
    mapRef.current?.startDrawing()
  }

  function handleFinishDrawing() {
    const ring = mapRef.current?.finishDrawing() ?? null
    setDrawingActive(false)
    if (!ring) {
      setDrawError('Desenhe pelo menos 3 pontos antes de concluir.')
      pendingBoundaryCallbackRef.current = null
      return
    }
    pendingBoundaryCallbackRef.current?.(
      JSON.stringify({ type: 'Polygon', coordinates: [ring] }),
    )
    pendingBoundaryCallbackRef.current = null
  }

  function handleCancelDrawing() {
    mapRef.current?.cancelDrawing()
    setDrawingActive(false)
    pendingBoundaryCallbackRef.current = null
  }

  function handleStartPickLocation(onPicked: (latitude: number, longitude: number) => void) {
    setPickingLocation(true)
    mapRef.current?.startPointPick((latitude, longitude) => {
      setPickingLocation(false)
      onPicked(latitude, longitude)
    })
  }

  function handleCancelPickLocation() {
    mapRef.current?.cancelPointPick()
    setPickingLocation(false)
  }

  async function handleEnablePush() {
    setPushStatus('subscribing')
    setPushError(null)
    try {
      await subscribeToPush()
      setPushStatus('on')
    } catch (err) {
      setPushStatus('error')
      setPushError(err instanceof Error ? err.message : 'Não foi possível ativar notificações')
    }
  }

  async function handleDeleteAccount() {
    if (
      !window.confirm(
        'Excluir sua conta é permanente e apaga todos os seus locais, alertas e histórico. Tem certeza?',
      )
    ) {
      return
    }
    setDeletingAccount(true)
    try {
      await api.deleteAccount()
    } catch {
      // Even if the request itself failed after the account was gone
      // (e.g. token already invalid), logging out locally is still correct.
    }
    onLogout()
  }

  async function handleResendVerification() {
    setVerificationSent(null)
    try {
      const { sent } = await resendVerification()
      setVerificationSent(sent ? 'sent' : 'already-verified')
    } catch {
      setVerificationSent('error')
    }
  }

  const mock = storms.some((s) => s.is_mock)
  const selectedLocation = locations.find((l) => l.id === selectedLocationId) ?? null
  const { entries: agroEntries, activeLocations: agroActiveLocations } = useAgroEntries(locations)
  const plotBoundaries: PlotBoundary[] = locations.flatMap((l) => {
    if (!l.boundary_geojson) return []
    try {
      const parsed = JSON.parse(l.boundary_geojson) as { coordinates: [number, number][][] }
      return [
        {
          id: l.id,
          name: l.name,
          color: l.color ?? cropColor(l.crop),
          coordinates: parsed.coordinates,
        },
      ]
    } catch {
      return []
    }
  })

  if (showAdmin) {
    return <AdminPanel onBack={() => setShowAdmin(false)} meId={me?.id ?? null} />
  }

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
        {me?.is_platform_admin && (
          <button className="btn ghost" onClick={() => setShowAdmin(true)}>
            🛠️ Admin
          </button>
        )}
        {isPushSupported() && pushStatus !== 'on' && (
          <button
            className="btn ghost"
            onClick={handleEnablePush}
            disabled={pushStatus === 'subscribing'}
            title={pushError ?? undefined}
          >
            {pushStatus === 'subscribing' ? 'Ativando…' : '🔔 Ativar notificações'}
          </button>
        )}
        {pushStatus === 'on' && <span className="pill">🔔 Notificações ativas</span>}
        <button className="btn ghost" onClick={() => setShowApiKeys(true)}>
          🔑 API
        </button>
        <button className="btn ghost" onClick={handleDeleteAccount} disabled={deletingAccount}>
          {deletingAccount ? 'Excluindo…' : 'Excluir conta'}
        </button>
        <button className="btn ghost" onClick={onLogout}>
          Sair
        </button>
      </header>

      {showApiKeys && <ApiKeysModal onClose={() => setShowApiKeys(false)} />}

      <div className="dashboard-body">
        {me && !me.email_verified && (
          <div className="panel">
            ✉️ Confirme seu e-mail para garantir acesso total à sua conta.{' '}
            {verificationSent === 'sent' ? (
              <span className="muted">Link reenviado — confira sua caixa de entrada.</span>
            ) : verificationSent === 'already-verified' ? (
              <span className="muted">Seu e-mail já foi confirmado — atualize a página.</span>
            ) : verificationSent === 'error' ? (
              <span className="error">Falha ao reenviar. Tente de novo em instantes.</span>
            ) : (
              <button type="button" className="link-btn" onClick={handleResendVerification}>
                Reenviar e-mail de confirmação
              </button>
            )}
          </div>
        )}
        {error && <div className="panel error">⚠️ {error}</div>}
        {pushStatus === 'error' && pushError && (
          <div className="panel error">🔔 {pushError}</div>
        )}

        <div className="top-cards">
          <LocationSearchCard
            locations={locations}
            selectedLocationId={selectedLocationId}
            onSelectLocation={(id) => {
              setSelectedLocationId(id)
              const loc = locations.find((l) => l.id === id)
              if (loc) mapRef.current?.flyTo(loc.latitude, loc.longitude)
            }}
            onLocationCreated={handleLocationCreated}
            onLocationUpdated={handleLocationUpdated}
            onLocationDeleted={handleLocationDeleted}
            onStartDrawBoundary={handleStartDrawBoundary}
            onStartPickLocation={handleStartPickLocation}
            plotCreationEnabled={activeTab === 'agro'}
            showPlots={activeTab === 'agro'}
          />
          <LocationWeatherCard location={selectedLocation} />
        </div>

        {/* Module selection (FASE 30): only show the switcher when the
            tenant actually has both — a single-module tenant just sees
            that module's content directly, no tab to switch to. */}
        {(me?.storm_module_enabled ?? true) && (me?.agro_module_enabled ?? false) && (
          <div className="tab-switcher" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'storm'}
              className={`tab-button ${activeTab === 'storm' ? 'active' : ''}`}
              onClick={() => setActiveTab('storm')}
            >
              ⛈️ Tempestade
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'agro'}
              className={`tab-button ${activeTab === 'agro' ? 'active' : ''}`}
              onClick={() => setActiveTab('agro')}
            >
              🌾 Agro
            </button>
          </div>
        )}

        {activeTab === 'storm' ? (
          <div className="top-cards secondary">
            <AlertsPanel
              alerts={alerts.filter((a) => !AGRO_ALERT_EVENT_TYPES.has(a.event_type))}
            />
            <StormsPanel storms={storms} />
            <SatelliteWatchesPanel
              watches={satelliteWatches}
              hasImage={satelliteImage !== null}
              locations={locations.filter((l) => l.is_active)}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <LightningPanel
              strikes={lightning}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <InstabilityPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
          </div>
        ) : (
          <div className="top-cards secondary">
            <FrostPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <SprayWindowPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <RainfallPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <TrafficabilityPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <WaterBalancePanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <DiseaseRiskPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <NdviPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
            <ZarcPanel
              activeLocations={agroActiveLocations}
              entries={agroEntries}
              onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
            />
          </div>
        )}

        <div className="map-card">
          <StormMap
            ref={mapRef}
            storms={storms}
            locations={locations}
            satelliteWatches={satelliteWatches}
            satelliteImage={showSatelliteImage ? satelliteImage : null}
            lightning={lightning}
            plotBoundaries={plotBoundaries}
            satelliteBasemap={satelliteBasemap}
          />
          {drawingActive && (
            <div className="draw-mode-bar">
              <span>🖊️ Clique no mapa pra marcar os cantos do talhão</span>
              <button className="btn small" onClick={handleFinishDrawing}>
                Concluir
              </button>
              <button className="btn ghost small" onClick={handleCancelDrawing}>
                Cancelar
              </button>
            </div>
          )}
          {drawError && !drawingActive && (
            <div className="draw-mode-bar error">
              ⚠️ {drawError}
              <button className="btn ghost small" onClick={() => setDrawError(null)}>
                ok
              </button>
            </div>
          )}
          {pickingLocation && (
            <div className="draw-mode-bar">
              <span>📍 Clique no mapa pra marcar o local</span>
              <button className="btn ghost small" onClick={handleCancelPickLocation}>
                Cancelar
              </button>
            </div>
          )}

          <button
            type="button"
            className="legend-toggle"
            onClick={() => setShowLegend((v) => !v)}
            title={showLegend ? 'Ocultar legenda' : 'Mostrar legenda'}
          >
            {showLegend ? '✕ legenda' : '☰ legenda'}
          </button>

          {showLegend && (
            <div className="map-legend">
              <label className="legend-item satellite-image-toggle">
                <input
                  type="checkbox"
                  checked={satelliteBasemap}
                  onChange={(e) => setSatelliteBasemap(e.target.checked)}
                />
                🛰️ imagem de satélite (mapa)
              </label>
              {satelliteBasemap && (
                <span className="legend-item satellite-image-hint">
                  cinza = nuvem comum · amarelo→laranja→vermelho→magenta = topo cada vez mais
                  frio (risco de tempestade)
                </span>
              )}
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
              {lightning.length > 0 && (
                <span className="legend-item">
                  <span className="swatch" style={{ background: '#fde047' }} /> raios (
                  {lightning.length})
                </span>
              )}
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
          )}
        </div>

        {updatedAt && (
          <div className="updated">
            Atualizado {formatTimeBR(updatedAt)} · atualização automática 30s
          </div>
        )}
        <SafetyDisclaimer />
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
            <span className={`badge ${a.level}`}>{riskLevelLabel(a.level)}</span>
            <div className="grow">
              <div>{a.title}</div>
              <div className="sub">{a.message}</div>
              <div className="sub muted">{timeAgo(a.created_at)}</div>
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
                {formatTimeBR(s.detected_at)}
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

/** Among the watched locations, picks the one this cell is heading toward
 * and closest to (if any), for the "chegada estimada" label. */
function bestStormEtaLabel(watch: ConvectiveWatch, locations: LocationItem[]): string | null {
  let best: { name: string; etaMinutes: number } | null = null
  for (const loc of locations) {
    const eta = estimateStormEta(
      watch.latitude,
      watch.longitude,
      watch.speed_kmh,
      watch.direction_deg,
      loc.latitude,
      loc.longitude,
    )
    if (eta && (best == null || eta.etaMinutes < best.etaMinutes)) {
      best = { name: loc.name, etaMinutes: eta.etaMinutes }
    }
  }
  if (!best) return null
  const minutes = Math.round(best.etaMinutes)
  return minutes < 60
    ? `chegada estimada em ~${minutes} min em ${best.name}`
    : `chegada estimada em ~${(minutes / 60).toFixed(1)}h em ${best.name}`
}

function SatelliteWatchesPanel({
  watches,
  hasImage,
  locations,
  onSelect,
}: {
  watches: ConvectiveWatch[]
  hasImage: boolean
  locations: LocationItem[]
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
        {watches.length === 0 && hasImage && (
          <p className="empty">
            Nenhuma célula com resfriamento de topo detectada na área monitorada agora.
          </p>
        )}
        {watches.length === 0 && !hasImage && (
          <p className="empty">
            Nenhuma observação ativa (ainda sem imagem de satélite — pipeline não rodou ou
            SATELLITE_ENABLED=false, ver README).
          </p>
        )}
        {watches.map((w) => (
          <SatelliteWatchRow
            key={w.id}
            watch={w}
            onSelect={onSelect}
            etaLabel={bestStormEtaLabel(w, locations)}
          />
        ))}
      </div>
    </section>
  )
}

function InstabilityPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        🌩️ Instabilidade <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">
        CAPE (energia disponível para tempestade formar), por local — não é uma previsão por si
        só, é um ingrediente.
      </p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          const label: Record<CapeLevel, string> = {
            weak: 'fraca',
            moderate: 'moderada',
            strong: 'forte',
            extreme: 'extrema',
          }
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
                    {entry.capeJkg != null && entry.capeLevel != null ? (
                      <div
                        className={`agro-row ${entry.capeLevel === 'strong' || entry.capeLevel === 'extreme' ? 'warn' : ''}`}
                      >
                        CAPE {entry.capeJkg.toFixed(0)} J/kg — instabilidade {label[entry.capeLevel]}
                        {entry.windGustMaxKmh != null
                          ? ` · rajada prevista ${entry.windGustMaxKmh.toFixed(0)} km/h`
                          : ''}
                      </div>
                    ) : (
                      <div className="agro-row sub">CAPE indisponível no momento.</div>
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

const LIGHTNING_PREVIEW_SIZE = 8

function LightningPanel({
  strikes,
  onSelect,
}: {
  strikes: LightningStrike[]
  onSelect: (latitude: number, longitude: number) => void
}) {
  return (
    <section className="panel">
      <h2>
        ⚡ Raios <span className="count">{strikes.length}</span>
      </h2>
      <p className="panel-hint">
        Descargas atmosféricas detectadas nos últimos ~30 minutos (API-REDEMET). Clique num raio
        para ver no mapa.
      </p>
      <div className="list">
        {strikes.length === 0 && <p className="empty">Nenhum raio detectado no momento.</p>}
        {strikes.slice(0, LIGHTNING_PREVIEW_SIZE).map((s) => (
          <div
            className="row clickable"
            key={s.id}
            onClick={() => onSelect(s.latitude, s.longitude)}
            role="button"
            tabIndex={0}
          >
            <div className="grow">
              <div>
                {s.latitude.toFixed(2)}, {s.longitude.toFixed(2)}
              </div>
              <div className="sub">{timeAgo(s.detected_at)}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// Mirrors the backend defaults (AGRO_FROST_THRESHOLD_C/
// AGRO_FROST_LIGHT_THRESHOLD_C) for the client-side derivation below —
// generic agronomic references, not crop-specific; see ADR-0014/ADR-0018.
// Not fetched dynamically: same reasoning as other thresholds already
// baked into this dashboard.
const FROST_THRESHOLD_C = 3
const FROST_LIGHT_THRESHOLD_C = 6
const TRAFFICABILITY_DRY_DAYS = 2
const TRAFFICABILITY_RAIN_THRESHOLD_MM = 1
const TRAFFICABILITY_LOOKAHEAD_DAYS = 2
// Generic base temperature for GDD (not crop-specific — same philosophy as
// the frost/dry-spell thresholds above) and the fungal disease-risk proxy
// thresholds (FASE 25, ADR-0021): humid + mild favors fungal growth.
const GDD_BASE_TEMP_C = 10
const DISEASE_RISK_THRESHOLDS = { humidityThresholdPercent: 80, minTempC: 15, maxTempC: 30 }

interface AgroEntry {
  severeFrostDays: ForecastPoint[]
  lightFrostDays: ForecastPoint[]
  sprayWindow: SprayWindow | null
  rainfallTotalMm: number | null
  rainfallDays: number
  trafficability: Trafficability | null
  capeJkg: number | null
  capeLevel: CapeLevel | null
  windGustMaxKmh: number | null
  waterBalanceMm: number | null
  gddC: number | null
  diseaseRisk: DiseaseRisk
  vpdKpa: number | null
  vpdLevel: VpdLevel
  ndvi: NdviReading | null
  ndviLevel: NdviLevel
  zarcWindow: ZarcWindow | null
  error: string | null
}

const EMPTY_AGRO_DERIVED = {
  capeJkg: null,
  capeLevel: null,
  windGustMaxKmh: null,
  waterBalanceMm: null,
  gddC: null,
  diseaseRisk: 'unknown' as DiseaseRisk,
  vpdKpa: null,
  vpdLevel: 'unknown' as VpdLevel,
}

/** Derives the CAPE/water-balance/GDD/disease-risk/VPD/gust signals
 * (FASE 25, ADR-0021) from today's Open-Meteo-exclusive forecast point —
 * `rainForecast` is always Open-Meteo (ADR-0020), so this is the one place
 * these fields are reliably populated regardless of which source answers
 * the general `/forecast` call. */
function deriveAgroSignals(todayPoint: ForecastPoint | null) {
  if (!todayPoint) return EMPTY_AGRO_DERIVED
  const capeJkg = todayPoint.cape_max_jkg
  const et0Mm = todayPoint.evapotranspiration_mm
  const rainTodayMm = todayPoint.precipitation_mm
  const tempMeanC = todayPoint.temperature_mean_c
  const humidityMeanPercent = todayPoint.humidity_mean_percent
  const vpdKpa =
    tempMeanC != null && humidityMeanPercent != null
      ? vaporPressureDeficitKpa(tempMeanC, humidityMeanPercent)
      : null
  return {
    capeJkg,
    capeLevel: capeJkg != null ? classifyCape(capeJkg) : null,
    windGustMaxKmh: todayPoint.wind_gusts_max_kmh,
    waterBalanceMm:
      et0Mm != null && rainTodayMm != null ? waterBalanceMm(rainTodayMm, et0Mm) : null,
    gddC: tempMeanC != null ? growingDegreeDays(tempMeanC, GDD_BASE_TEMP_C) : null,
    diseaseRisk: classifyDiseaseRisk(humidityMeanPercent, tempMeanC, DISEASE_RISK_THRESHOLDS),
    vpdKpa,
    vpdLevel: vpdKpa != null ? classifyVpd(vpdKpa) : ('unknown' as VpdLevel),
  }
}

function useAgroEntries(locations: LocationItem[]): {
  entries: Record<string, AgroEntry>
  activeLocations: LocationItem[]
} {
  const [entries, setEntries] = useState<Record<string, AgroEntry>>({})
  const activeLocations = locations.filter((l) => l.is_active)
  const activeIds = activeLocations.map((l) => l.id).join(',')

  useEffect(() => {
    let cancelled = false
    const active = locations.filter((l) => l.is_active)

    async function load() {
      const results = await Promise.all(
        active.map(async (l): Promise<[string, AgroEntry]> => {
          try {
            const isTalhaoWithBoundary = l.parent_location_id != null && l.boundary_geojson != null
            // ZARC (item ZARC, ADR-0069) only has an answer for a talhão
            // with both crop and soil_type set — skip the call otherwise
            // instead of hitting an endpoint that would just 404 every
            // refresh cycle.
            const isTalhaoWithCropAndSoil =
              l.parent_location_id != null && l.crop != null && l.soil_type != null
            const [forecast, sprayWindow, rainfall, rainForecast, ndvi, zarcWindow] =
              await Promise.all([
                api.forecast(l.id).catch(() => null),
                api.sprayWindow(l.id).catch(() => null),
                api.rainfall(l.id).catch(() => null),
                // Always Open-Meteo (bypasses INMET/CPTEC, ADR-0020) — the
                // general forecast above often comes from CPTEC instead
                // (whenever INMET is down), which never has a rain number
                // at all, so trafficability would otherwise almost always
                // come back "unknown" even when Open-Meteo has the answer.
                api.rainForecast(l.id).catch(() => null),
                // Only talhões (a plot with a drawn boundary) ever have
                // NDVI data (FASE 29, ADR-0053) — skip the call entirely
                // for a farm-level point instead of hitting an endpoint
                // that would just 404 every refresh cycle.
                isTalhaoWithBoundary ? api.ndvi(l.id).catch(() => null) : Promise.resolve(null),
                isTalhaoWithCropAndSoil
                  ? api.zarcWindow(l.id).catch(() => null)
                  : Promise.resolve(null),
              ])
            const { severe, light } = classifyFrostDays(
              forecast?.points ?? [],
              FROST_THRESHOLD_C,
              FROST_LIGHT_THRESHOLD_C,
            )
            const today = new Date()
            today.setHours(0, 0, 0, 0)
            const upcomingRain = (rainForecast?.points ?? []).filter(
              (p) => new Date(p.time) >= today,
            )
            return [
              l.id,
              {
                severeFrostDays: severe,
                lightFrostDays: light,
                sprayWindow,
                rainfallTotalMm: rainfall
                  ? rainfall.daily.reduce((sum, d) => sum + d.total_mm, 0)
                  : null,
                rainfallDays: rainfall?.daily.length ?? 0,
                trafficability: rainfall
                  ? evaluateTrafficability(rainfall.daily, upcomingRain, {
                      requiredDryDays: TRAFFICABILITY_DRY_DAYS,
                      rainThresholdMm: TRAFFICABILITY_RAIN_THRESHOLD_MM,
                      lookaheadDays: TRAFFICABILITY_LOOKAHEAD_DAYS,
                    })
                  : null,
                ...deriveAgroSignals(upcomingRain[0] ?? null),
                ndvi,
                ndviLevel: classifyNdvi(ndvi?.ndvi_mean ?? null),
                zarcWindow,
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
                severeFrostDays: [],
                lightFrostDays: [],
                sprayWindow: null,
                rainfallTotalMm: null,
                rainfallDays: 0,
                trafficability: null,
                ...EMPTY_AGRO_DERIVED,
                ndvi: null,
                ndviLevel: 'unknown' as NdviLevel,
                zarcWindow: null,
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

  return { entries, activeLocations }
}

interface AgroPanelProps {
  activeLocations: LocationItem[]
  entries: Record<string, AgroEntry>
  onSelect: (latitude: number, longitude: number) => void
}

function FrostPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        ❄️ Geada <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">
        Forte (≤{FROST_THRESHOLD_C}°C) e risco leve (≤{FROST_LIGHT_THRESHOLD_C}°C), por local.
      </p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          const hasFrost =
            entry && (entry.severeFrostDays.length > 0 || entry.lightFrostDays.length > 0)
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
                    {entry.severeFrostDays.length > 0 && (
                      <div className="agro-row warn">Forte: {formatFrostDays(entry.severeFrostDays)}</div>
                    )}
                    {entry.lightFrostDays.length > 0 && (
                      <div className="agro-row warn">Leve: {formatFrostDays(entry.lightFrostDays)}</div>
                    )}
                    {!hasFrost && <div className="agro-row sub">Sem risco de geada previsto.</div>}
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

function SprayWindowPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        🌬️ Pulverização <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">Vento, umidade e chuva prevista, por local.</p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          const sprayWindow = entry?.sprayWindow ?? null
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
                    {sprayWindow ? (
                      <div className={`agro-row ${sprayWindow.safe === false ? 'warn' : ''}`}>
                        {sprayWindow.wind_kmh != null
                          ? `vento ${sprayWindow.wind_kmh.toFixed(0)} km/h`
                          : 'vento indisponível'}
                        {sprayWindow.wind_gusts_kmh != null
                          ? ` (rajada ${sprayWindow.wind_gusts_kmh.toFixed(0)} km/h)`
                          : ''}{' '}
                        —{' '}
                        {sprayWindow.safe == null
                          ? 'não avaliável'
                          : sprayWindow.safe
                            ? 'janela segura pra pulverizar'
                            : sprayWindow.inversion_risk
                              ? 'risco de inversão térmica (vento calmo + umidade alta)'
                              : sprayWindow.rain_probability_percent != null &&
                                  sprayWindow.rain_probability_percent >=
                                    sprayWindow.max_rain_probability_percent
                                ? `chuva provável (${sprayWindow.rain_probability_percent}%)`
                                : `vento acima do limite de ${sprayWindow.max_wind_kmh.toFixed(0)} km/h`}
                      </div>
                    ) : (
                      <div className="agro-row sub">Dado de vento indisponível.</div>
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

function RainfallPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        🌧️ Chuva acumulada <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">Total dos últimos dias, por local.</p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
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
                    {entry.rainfallTotalMm != null ? (
                      <div className="agro-row">
                        {entry.rainfallTotalMm.toFixed(0)}mm acumulados ({entry.rainfallDays} dias)
                      </div>
                    ) : (
                      <div className="agro-row sub">Histórico de chuva indisponível.</div>
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

function WaterBalancePanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        💧 Balanço hídrico <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">
        Chuva menos evapotranspiração de hoje (ET0), e graus-dia acumulados (base {GDD_BASE_TEMP_C}
        °C), por local.
      </p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
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
                    {entry.waterBalanceMm != null ? (
                      <div className={`agro-row ${entry.waterBalanceMm < 0 ? 'warn' : ''}`}>
                        {entry.waterBalanceMm >= 0 ? '+' : ''}
                        {entry.waterBalanceMm.toFixed(1)}mm hoje
                      </div>
                    ) : (
                      <div className="agro-row sub">Balanço hídrico indisponível.</div>
                    )}
                    {entry.gddC != null ? (
                      <div className="agro-row">{entry.gddC.toFixed(1)} graus-dia hoje</div>
                    ) : (
                      <div className="agro-row sub">Graus-dia indisponível.</div>
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

function DiseaseRiskPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        🦠 Risco de doença <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">
        Umidade alta + temperatura amena favorecem fungos (estimativa diária simplificada); déficit
        de pressão de vapor (VPD) indica estresse hídrico da planta.
      </p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          const vpdLabel: Record<VpdLevel, string> = {
            low: 'baixo (transpiração reduzida)',
            ideal: 'ideal',
            high: 'alto (estresse hídrico)',
            unknown: 'indisponível',
          }
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
                    <div className={`agro-row ${entry.diseaseRisk === 'high' ? 'warn' : ''}`}>
                      {entry.diseaseRisk === 'high'
                        ? 'risco elevado de doença fúngica'
                        : entry.diseaseRisk === 'low'
                          ? 'risco baixo de doença fúngica'
                          : 'risco de doença indisponível'}
                    </div>
                    <div className={`agro-row ${entry.vpdLevel === 'high' ? 'warn' : ''}`}>
                      VPD {entry.vpdKpa != null ? `${entry.vpdKpa.toFixed(2)} kPa — ` : ''}
                      {vpdLabel[entry.vpdLevel]}
                    </div>
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

/** Only ever shows talhões (a plot with a drawn boundary) — NDVI has no
 * meaning for a farm-level point (FASE 29, ADR-0053). Deliberately its own
 * filtered subset of `activeLocations`, not a new prop threaded through
 * `AgroPanelProps` — every other agro panel still applies to farms and
 * plots alike. */
function NdviPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  const talhoes = activeLocations.filter(
    (l) => l.parent_location_id != null && l.boundary_geojson != null,
  )
  return (
    <section className="panel">
      <h2>
        🌿 NDVI (talhões) <span className="count">{talhoes.length}</span>
      </h2>
      <p className="panel-hint">
        Índice de vegetação por satélite (Sentinel-2) — só disponível para talhões com contorno
        desenhado no mapa.
      </p>
      <div className="list">
        {talhoes.length === 0 && (
          <p className="empty">Nenhum talhão com contorno desenhado ainda.</p>
        )}
        {talhoes.map((l) => {
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
                {entry && (
                  <div className="agro-section">
                    {entry.ndvi && entry.ndvi.ndvi_mean != null ? (
                      <div className="agro-row">
                        NDVI {entry.ndvi.ndvi_mean.toFixed(2)} —{' '}
                        {formatDateBR(entry.ndvi.observed_at, {
                          day: '2-digit',
                          month: '2-digit',
                        })}{' '}
                        — {NDVI_LABEL[entry.ndviLevel]}
                        {entry.ndvi.is_mock && ' (simulado)'}
                      </div>
                    ) : (
                      <div className="agro-row sub">{NDVI_LABEL.unknown}</div>
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

/** Only ever shows talhões with both crop and soil_type set — ZARC has no
 * meaning for a farm-level point or a talhão missing either field (item
 * ZARC, ADR-0069). Purely informational: no alert is derived from it,
 * there's no planting-date field to compare the windows against yet. */
function ZarcPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  const talhoes = activeLocations.filter(
    (l) => l.parent_location_id != null && l.crop != null && l.soil_type != null,
  )
  return (
    <section className="panel">
      <h2>
        🌱 Janela de Plantio (ZARC) <span className="count">{talhoes.length}</span>
      </h2>
      <p className="panel-hint">
        Zoneamento Agrícola de Risco Climático (MAPA) — só disponível para talhões com cultura e
        tipo de solo informados. Informativo, não gera alerta.
      </p>
      <div className="list">
        {talhoes.length === 0 && (
          <p className="empty">Nenhum talhão com cultura e tipo de solo informados ainda.</p>
        )}
        {talhoes.map((l) => {
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
                {entry && (
                  <div className="agro-section">
                    {entry.zarcWindow && entry.zarcWindow.matches.length > 0 ? (
                      entry.zarcWindow.matches.map((m) => (
                        <div
                          className="agro-row"
                          key={`${m.cultura}-${m.cod_ciclo}`}
                        >
                          {m.cultura} ({m.ciclo_label}) — safra {m.safra_ini}/{m.safra_fin}
                          {m.portaria && ` — ${m.portaria}`}
                        </div>
                      ))
                    ) : (
                      <div className="agro-row sub">
                        Nenhuma janela ZARC encontrada para este talhão
                      </div>
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

function TrafficabilityPanel({ activeLocations, entries, onSelect }: AgroPanelProps) {
  return (
    <section className="panel">
      <h2>
        🚜 Trafegabilidade <span className="count">{activeLocations.length}</span>
      </h2>
      <p className="panel-hint">Solo seco o bastante para manejo/colheita, por local.</p>
      <div className="list">
        {activeLocations.length === 0 && <p className="empty">Nenhum local monitorado ativo.</p>}
        {activeLocations.map((l) => {
          const entry = entries[l.id]
          const trafficability = entry?.trafficability ?? null
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
                    {trafficability === 'trafficable' && (
                      <div className="agro-row">Solo seco — favorável para manejo/colheita.</div>
                    )}
                    {trafficability === 'not_trafficable' && (
                      <div className="agro-row warn">
                        Solo úmido ou chuva prevista — evitar manejo pesado.
                      </div>
                    )}
                    {trafficability === 'unknown' && (
                      <div className="agro-row sub">
                        Chuva prevista indisponível no momento (fonte ativa não fornece número).
                      </div>
                    )}
                    {trafficability == null && (
                      <div className="agro-row sub">Sem dado suficiente pra avaliar.</div>
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
