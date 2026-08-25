import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, publicApi, VISITOR_SEARCH_RADIUS_KM } from '../api'
import { timeAgo } from '../format'
import { reverseGeocodeCity, searchCity } from '../geocode'
import { SafetyDisclaimer } from './SafetyDisclaimer'
import { SatelliteWatchRow } from './SatelliteWatchRow'
import type {
  CitySearchResult,
  ConvectiveWatch,
  LightningStrike,
  LocationItem,
  SatelliteImageMeta,
  StormCell,
  WarningItem,
} from '../types'
import { StormMap, type StormMapHandle } from './LazyStormMap'

interface Props {
  onBack: () => void
}

const REFRESH_MS = 30_000
const SEARCH_DEBOUNCE_MS = 400

// Same reference point StormMap itself centers on by default — a visitor
// who hasn't searched their own city yet sees this instead.
const DEFAULT_REFERENCE = { label: 'São Paulo, SP (referência padrão)', lat: -23.55, lon: -46.63 }

export function VisitorView({ onBack }: Props) {
  const mapRef = useRef<StormMapHandle>(null)
  const [storms, setStorms] = useState<StormCell[]>([])
  const [warnings, setWarnings] = useState<WarningItem[]>([])
  const [satelliteWatches, setSatelliteWatches] = useState<ConvectiveWatch[]>([])
  const [satelliteImage, setSatelliteImage] = useState<SatelliteImageMeta | null>(null)
  const [showSatelliteImage, setShowSatelliteImage] = useState(true)
  const [lightning, setLightning] = useState<LightningStrike[]>([])
  const [error, setError] = useState<string | null>(null)

  // Visitor mode has no account/monitored location — the reference point
  // for "Avisos oficiais" starts at a fixed default (São Paulo) but can be
  // moved to wherever the visitor actually is, same search UX logged-in
  // users get for adding a location (FASE 33).
  const [reference, setReference] = useState(DEFAULT_REFERENCE)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CitySearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [locating, setLocating] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Not a real monitored location (visitor mode has none — no account) —
  // just enough of the shape StormMap expects to draw a marker at the
  // chosen point. `radius_km` isn't actually rendered as a circle by
  // StormMap today (it only draws a fixed-size dot), but it's set to
  // VISITOR_SEARCH_RADIUS_KM anyway so it stays honest if that ever changes.
  const referenceMarker = useMemo<LocationItem>(
    () => ({
      id: 'visitor-reference',
      name: reference.label,
      kind: 'reference',
      latitude: reference.lat,
      longitude: reference.lon,
      radius_km: VISITOR_SEARCH_RADIUS_KM,
      is_active: true,
      created_at: new Date().toISOString(),
      alert_preferences: [],
      parent_location_id: null,
      crop: null,
      boundary_geojson: null,
      color: null,
    }),
    [reference],
  )

  // The satellite image is one frame covering a fixed region for the whole
  // deployment (SATELLITE_EXTENT), not something that follows any single
  // visitor — a chosen point outside that region shows stale/wrong-looking
  // imagery with no indication why. Flagged explicitly rather than left
  // silent (FASE 34 follow-up: user asked whether cloud cover over their
  // city would show up here).
  const outsideSatelliteCoverage = useMemo(() => {
    if (!satelliteImage) return false
    const [lonMin, latMin, lonMax, latMax] = satelliteImage.bbox
    return (
      reference.lon < lonMin ||
      reference.lon > lonMax ||
      reference.lat < latMin ||
      reference.lat > latMax
    )
  }, [satelliteImage, reference])

  const load = useCallback(async () => {
    try {
      const [stormsRes, warningsRes, satelliteRes, satelliteImageRes, lightningRes] =
        await Promise.all([
          publicApi.storms(reference.lat, reference.lon),
          publicApi.warnings(reference.lat, reference.lon),
          publicApi.satelliteWatches(reference.lat, reference.lon),
          publicApi.satelliteImage(),
          publicApi.lightning(reference.lat, reference.lon),
        ])
      setStorms(stormsRes)
      setWarnings(warningsRes)
      setSatelliteWatches(satelliteRes)
      setSatelliteImage(satelliteImageRes)
      setLightning(lightningRes)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erro ao carregar')
    }
  }, [reference])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    mapRef.current?.flyTo(reference.lat, reference.lon)
  }, [reference])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      setResults(await searchCity(query))
      setSearching(false)
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  function pickCity(r: CitySearchResult) {
    setReference({ label: r.label.split(',').slice(0, 2).join(','), lat: r.latitude, lon: r.longitude })
    setResults([])
    setQuery('')
  }

  function useMyLocation() {
    if (!navigator.geolocation) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        reverseGeocodeCity(latitude, longitude, (place) => {
          setLocating(false)
          setReference({
            label: place ?? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`,
            lat: latitude,
            lon: longitude,
          })
        })
      },
      () => setLocating(false),
      { timeout: 10_000 },
    )
  }

  const mock = storms.some((s) => s.is_mock)

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        <span className="pill">Modo visitante</span>
        {mock && <span className="mock-tag">DADOS MOCK</span>}
        <div className="spacer" />
        <button className="btn ghost" onClick={onBack}>
          Criar conta / Entrar
        </button>
      </header>

      <div className="layout">
        <div className="map-card">
          <StormMap
            ref={mapRef}
            storms={storms}
            locations={[referenceMarker]}
            satelliteWatches={satelliteWatches}
            satelliteImage={showSatelliteImage ? satelliteImage : null}
            lightning={lightning}
          />
          {(satelliteImage || lightning.length > 0) && (
            <div className="map-legend">
              {lightning.length > 0 && (
                <span className="legend-item">
                  <span className="swatch" style={{ background: '#fde047' }} /> raios (
                  {lightning.length})
                </span>
              )}
              {satelliteImage && (
                <label className="legend-item satellite-image-toggle standalone">
                  <input
                    type="checkbox"
                    checked={showSatelliteImage}
                    onChange={(e) => setShowSatelliteImage(e.target.checked)}
                  />
                  imagem de satélite (IR) · {timeAgo(satelliteImage.captured_at)}
                </label>
              )}
              {outsideSatelliteCoverage && (
                <span className="legend-item satellite-coverage-warning">
                  ⚠️ imagem de satélite não cobre {reference.label}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="side">
          {error && <div className="panel error">⚠️ {error}</div>}
          <section className="panel">
            <h2>📍 Sua região</h2>
            <p className="panel-hint">
              "Avisos oficiais" abaixo é buscado perto deste ponto — atualmente{' '}
              <strong>{reference.label}</strong>.
            </p>
            <div className="location-search-row">
              <input
                placeholder="Buscar cidade (ex: Ribeirão Preto)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button
                type="button"
                className="btn ghost small"
                onClick={useMyLocation}
                disabled={locating}
                title="Usar minha localização"
              >
                {locating ? '…' : '📍 usar minha localização'}
              </button>
            </div>
            {searching && <p className="panel-hint">buscando…</p>}
            {results.length > 0 && (
              <div className="list search-results">
                {results.map((r) => (
                  <div className="row clickable" key={`${r.latitude},${r.longitude}`} onClick={() => pickCity(r)}>
                    <span className="grow">{r.label}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="panel">
            <h2>
              Observações via satélite <span className="count">{satelliteWatches.length}</span>
            </h2>
            <p className="panel-hint">
              Nuvens esfriando no topo, vistas pelo satélite — sinal de que pode virar chuva, antes
              de aparecer como célula de tempestade. Clique numa observação para ver no mapa.
            </p>
            <div className="list">
              {satelliteWatches.length === 0 && satelliteImage && (
                <p className="empty">
                  Nenhuma célula com resfriamento de topo detectada na área monitorada agora.
                </p>
              )}
              {satelliteWatches.length === 0 && !satelliteImage && (
                <p className="empty">Nenhuma observação ativa no momento.</p>
              )}
              {satelliteWatches.slice(0, 8).map((w) => (
                <SatelliteWatchRow
                  key={w.id}
                  watch={w}
                  onSelect={(lat, lon) => mapRef.current?.flyTo(lat, lon)}
                />
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>
              Avisos oficiais <span className="count">{warnings.length}</span>
            </h2>
            <div className="list">
              {warnings.length === 0 && (
                <p className="empty">Nenhum aviso ativo perto de {reference.label}.</p>
              )}
              {warnings.map((w, i) => (
                <div className="row" key={i}>
                  <span className="badge sev">{w.severity}</span>
                  <div className="grow">
                    <div>{w.kind}</div>
                    <div className="sub">{w.description}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>
              Células detectadas <span className="count">{storms.length}</span>
            </h2>
            <div className="list">
              {storms.length === 0 && <p className="empty">Nenhuma célula no momento.</p>}
              {storms.slice(0, 8).map((s) => (
                <div className="row" key={s.id}>
                  <span className="badge sev">{s.severity}</span>
                  <div className="grow">
                    <div>
                      {s.latitude.toFixed(2)}, {s.longitude.toFixed(2)}
                    </div>
                    <div className="sub">
                      {s.max_reflectivity ? `${s.max_reflectivity.toFixed(0)} dBZ` : ''}
                    </div>
                  </div>
                  {s.is_mock && <span className="mock-tag">MOCK</span>}
                </div>
              ))}
            </div>
          </section>
          <p className="muted">
            Locais monitorados e alertas personalizados exigem uma conta.
          </p>
          <SafetyDisclaimer />
        </div>
      </div>
    </>
  )
}
