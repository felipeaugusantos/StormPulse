import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { formatDateBR } from '../format'
import type {
  LocationItem,
  VegetationComparison,
  VegetationIndex,
  VegetationReading,
  VegetationSeries,
} from '../types'

const INDICES: VegetationIndex[] = ['ndvi', 'ndre', 'evi', 'ndmi', 'ndwi']
const QUALITY = { high: 'alta', medium: 'média', low: 'baixa' } as const

export function VegetationIntelligencePanel({ locations }: { locations: LocationItem[] }) {
  const plots = useMemo(
    () =>
      locations.filter(
        (location) => location.parent_location_id != null && location.boundary_geojson != null,
      ),
    [locations],
  )
  const [locationId, setLocationId] = useState(plots[0]?.id ?? '')
  const [indexName, setIndexName] = useState<VegetationIndex>('ndvi')
  const [series, setSeries] = useState<VegetationSeries | null>(null)
  const [comparison, setComparison] = useState<VegetationComparison | null>(null)
  const [images, setImages] = useState<{ older: string; newer: string } | null>(null)
  const [olderDate, setOlderDate] = useState('')
  const [newerDate, setNewerDate] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!plots.some((plot) => plot.id === locationId)) setLocationId(plots[0]?.id ?? '')
  }, [locationId, plots])

  useEffect(() => {
    let active = true
    if (!locationId) return
    setLoading(true)
    setImages(null)
    Promise.all([
      api.vegetationSeries(locationId, indexName),
      api.vegetationComparison(locationId, indexName).catch(() => null),
    ])
      .then(async ([nextSeries, nextComparison]) => {
        if (!active) return
        setSeries(nextSeries)
        setComparison(nextComparison)
        if (nextComparison) {
          setOlderDate(nextComparison.older.observed_at.slice(0, 10))
          setNewerDate(nextComparison.newer.observed_at.slice(0, 10))
        } else {
          setOlderDate('')
          setNewerDate('')
        }
      })
      .catch(() => {
        if (active) {
          setSeries(null)
          setComparison(null)
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [indexName, locationId])

  useEffect(() => {
    let active = true
    const urls: string[] = []
    if (!comparison) {
      setImages(null)
      return
    }
    Promise.all([
      api.vegetationImage(locationId, indexName, comparison.older.observed_at),
      api.vegetationImage(locationId, indexName, comparison.newer.observed_at),
    ])
      .then((blobs) => {
        if (!active) return
        urls.push(...blobs.map((blob) => URL.createObjectURL(blob)))
        setImages({ older: urls[0], newer: urls[1] })
      })
      .catch(() => {
        if (active) setImages(null)
      })
    return () => {
      active = false
      urls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [comparison, indexName, locationId])

  const points = useMemo(() => sparklinePoints(series), [series])

  async function exportSeries() {
    if (!locationId) return
    const blob = await api.vegetationCsv(locationId, indexName)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${locationId}-${indexName}-series.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function compareDates() {
    if (!locationId || !olderDate || !newerDate) return
    setLoading(true)
    try {
      setComparison(
        await api.vegetationComparison(locationId, indexName, olderDate, newerDate),
      )
    } catch {
      setComparison(null)
      setImages(null)
    } finally {
      setLoading(false)
    }
  }

  const current = series?.current
  const reliableDates = series?.series.filter((item) => item.reliable) ?? []
  return (
    <section className="panel vegetation-panel">
      <h2>🛰️ Inteligência do talhão</h2>
      <p className="panel-hint">
        Sentinel-2 sobre o polígono completo. Aquisições com menos de 60% de pixels válidos não
        entram em anomalias, comparações ou alertas.
      </p>
      {plots.length === 0 ? (
        <p className="empty">Nenhum talhão com contorno desenhado ainda.</p>
      ) : (
        <>
          <div className="vegetation-controls">
            <label>
              Talhão
              <select value={locationId} onChange={(event) => setLocationId(event.target.value)}>
                {plots.map((plot) => (
                  <option key={plot.id} value={plot.id}>
                    {plot.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Índice
              <select
                value={indexName}
                onChange={(event) => setIndexName(event.target.value as VegetationIndex)}
              >
                {INDICES.map((index) => (
                  <option key={index} value={index}>
                    {index.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={exportSeries} disabled={!series?.series.length}>
              Exportar série CSV
            </button>
          </div>
          {loading && <p className="sub">Carregando histórico…</p>}
          {!loading && !current && <p className="empty">Nenhuma imagem válida disponível.</p>}
          {current && (
            <>
              <div className={`vegetation-current ${current.reliable ? '' : 'unreliable'}`}>
                <strong>
                  {current.index_name.toUpperCase()} {current.value_mean.toFixed(3)}
                </strong>
                <span>{current.source_name}</span>
                <span>{formatDateBR(current.observed_at)}</span>
                <span>qualidade {QUALITY[current.quality]}</span>
                <span>{current.cloud_cover_percent.toFixed(1)}% nuvens/sem dado</span>
                {current.is_mock && <strong>SIMULADO</strong>}
              </div>
              {!current.reliable && (
                <p className="quality-warning">
                  ⚠️ Imagem de baixa qualidade — não confiável para análise.
                </p>
              )}
              {points && (
                <svg
                  className="vegetation-chart"
                  viewBox="0 0 500 120"
                  role="img"
                  aria-label={`Série histórica ${indexName.toUpperCase()}`}
                >
                  <polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" />
                </svg>
              )}
              <p className="agro-row">
                {series.anomaly.status === 'insufficient_history'
                  ? `Anomalia indisponível: ${series.anomaly.baseline_count}/${series.anomaly.minimum_history} imagens confiáveis no histórico.`
                  : `Anomalia: ${series.anomaly.status.replace(/_/g, ' ')} (${series.anomaly.percent_difference?.toFixed(1) ?? '—'}%).`}
              </p>
              {series.persistent_drop && (
                <p className="quality-warning">⚠️ Queda persistente em três aquisições confiáveis.</p>
              )}
              {current.vigor_zones.length > 0 && (
                <div className="vigor-zones">
                  {current.vigor_zones.map((zone, position) => (
                    <span key={`${zone.label}-${position}`}>
                      {zone.label}: {zone.pixel_percent.toFixed(0)}%
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
          {reliableDates.length >= 2 && (
            <div className="vegetation-date-controls">
                <label>
                  Data anterior
                  <select value={olderDate} onChange={(event) => setOlderDate(event.target.value)}>
                    {reliableDates.map((item) => (
                      <option key={item.observed_at} value={item.observed_at.slice(0, 10)}>
                        {formatDateBR(item.observed_at)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Data atual
                  <select value={newerDate} onChange={(event) => setNewerDate(event.target.value)}>
                    {reliableDates.map((item) => (
                      <option key={item.observed_at} value={item.observed_at.slice(0, 10)}>
                        {formatDateBR(item.observed_at)}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" onClick={compareDates} disabled={!olderDate || !newerDate}>
                  Comparar datas
                </button>
            </div>
          )}
          {comparison && images && (
            <div className="vegetation-comparison">
                <ComparisonImage label="Anterior" reading={comparison.older} url={images.older} />
                <ComparisonImage label="Atual" reading={comparison.newer} url={images.newer} />
                <p>
                  Variação: {comparison.absolute_change >= 0 ? '+' : ''}
                  {comparison.absolute_change.toFixed(3)} ({comparison.percent_change?.toFixed(1) ?? '—'}%)
                </p>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function ComparisonImage({
  label,
  reading,
  url,
}: {
  label: string
  reading: VegetationReading
  url: string
}) {
  return (
    <figure>
      <img src={url} alt={`${label} — mapa ${reading.index_name.toUpperCase()}`} />
      <figcaption>
        {label}: {formatDateBR(reading.observed_at)} · {reading.source_name} · qualidade{' '}
        {QUALITY[reading.quality]}
      </figcaption>
      <a href={url} download={`${reading.index_name}-${reading.observed_at.slice(0, 10)}.png`}>
        Baixar mapa PNG
      </a>
    </figure>
  )
}

function sparklinePoints(series: VegetationSeries | null): string | null {
  const reliable = series?.series.filter((item) => item.reliable) ?? []
  if (reliable.length < 2) return null
  const values = reliable.map((item) => item.value_mean)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values
    .map(
      (value, index) =>
        `${(index / (values.length - 1)) * 500},${110 - ((value - min) / span) * 100}`,
    )
    .join(' ')
}
