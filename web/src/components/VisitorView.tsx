import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, publicApi } from '../api'
import { timeAgo } from '../format'
import { SatelliteWatchRow } from './SatelliteWatchRow'
import type { ConvectiveWatch, SatelliteImageMeta, StormCell, WarningItem } from '../types'
import { StormMap, type StormMapHandle } from './LazyStormMap'

interface Props {
  onBack: () => void
}

const REFRESH_MS = 30_000

// Same reference point StormMap itself centers on by default — visitor
// mode has no user location to go on, so warnings are scoped to here.
const REFERENCE_POINT = { lat: -23.55, lon: -46.63 }

export function VisitorView({ onBack }: Props) {
  const mapRef = useRef<StormMapHandle>(null)
  const [storms, setStorms] = useState<StormCell[]>([])
  const [warnings, setWarnings] = useState<WarningItem[]>([])
  const [satelliteWatches, setSatelliteWatches] = useState<ConvectiveWatch[]>([])
  const [satelliteImage, setSatelliteImage] = useState<SatelliteImageMeta | null>(null)
  const [showSatelliteImage, setShowSatelliteImage] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [stormsRes, warningsRes, satelliteRes, satelliteImageRes] = await Promise.all([
        publicApi.storms(),
        publicApi.warnings(REFERENCE_POINT.lat, REFERENCE_POINT.lon),
        publicApi.satelliteWatches(),
        publicApi.satelliteImage(),
      ])
      setStorms(stormsRes)
      setWarnings(warningsRes)
      setSatelliteWatches(satelliteRes)
      setSatelliteImage(satelliteImageRes)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erro ao carregar')
    }
  }, [])

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
            locations={[]}
            satelliteWatches={satelliteWatches}
            satelliteImage={showSatelliteImage ? satelliteImage : null}
          />
          {satelliteImage && (
            <div className="map-legend">
              <label className="legend-item satellite-image-toggle standalone">
                <input
                  type="checkbox"
                  checked={showSatelliteImage}
                  onChange={(e) => setShowSatelliteImage(e.target.checked)}
                />
                imagem de satélite (IR) · {timeAgo(satelliteImage.captured_at)}
              </label>
            </div>
          )}
        </div>

        <div className="side">
          {error && <div className="panel error">⚠️ {error}</div>}
          <section className="panel">
            <h2>
              Observações via satélite <span className="count">{satelliteWatches.length}</span>
            </h2>
            <p className="panel-hint">
              Nuvens esfriando no topo, vistas pelo satélite — sinal de que pode virar chuva, antes
              de aparecer como célula de tempestade. Clique numa observação para ver no mapa.
            </p>
            <div className="list">
              {satelliteWatches.length === 0 && (
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
              {warnings.length === 0 && <p className="empty">Nenhum aviso ativo perto de SP.</p>}
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
        </div>
      </div>
    </>
  )
}
