import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { ForecastComparison } from '../types'

interface Props {
  locationId: string
  locationName: string
  onClose: () => void
}

const MODEL_LABEL: Record<string, string> = {
  ecmwf_ifs025: 'ECMWF (IFS)',
  gfs_seamless: 'GFS (NOAA)',
  icon_seamless: 'ICON (DWD)',
}

function modelLabel(model: string): string {
  return MODEL_LABEL[model] ?? model
}

function fmt(value: number | null, digits = 1, suffix = ''): string {
  return value == null ? '—' : `${value.toFixed(digits)}${suffix}`
}

/** Comparação de acurácia entre modelos meteorológicos (Fase 2, ADR-0082) —
 * acumulada pelos jobs diários de snapshot/observação, nunca um cálculo ao
 * vivo. Uma localidade nova simplesmente ainda não tem modelo nenhum aqui;
 * isso é o estado honesto, não um erro. */
export function ForecastComparisonModal({ locationId, locationName, onClose }: Props) {
  const [comparison, setComparison] = useState<ForecastComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .forecastComparison(locationId)
      .then((c) => {
        if (!cancelled) setComparison(c)
      })
      .catch((err) => {
        if (cancelled) return
        setError(
          err instanceof ApiError ? err.message : 'Não foi possível carregar a comparação',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [locationId])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>📊 Comparação de modelos — {locationName}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading && <p className="panel-hint">carregando…</p>}
        {error && <p className="error">⚠️ {error}</p>}

        {comparison && (
          <>
            <p className="panel-hint">
              Acurácia de cada modelo neste talhão, medida contra o que realmente aconteceu —
              acumulada dia a dia, nunca um número instantâneo. Um modelo só é marcado como
              confiável a partir de {comparison.min_sample_size} previsões já confirmadas.
            </p>

            {comparison.models.length === 0 ? (
              <p className="panel-hint">
                Nenhum modelo tem previsões confirmadas ainda para este talhão — os dados se
                acumulam nos próximos dias.
              </p>
            ) : (
              <div className="list" style={{ marginTop: 8 }}>
                {comparison.models.map((m) => (
                  <div className="row" key={m.model} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                    <div className="grow" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <strong>{modelLabel(m.model)}</strong>
                      <span
                        className={`badge ${m.has_enough_samples ? 'green' : 'yellow'}`}
                        title={
                          m.has_enough_samples
                            ? 'Amostra suficiente para confiar nesta comparação'
                            : `Ainda com poucas amostras (${m.sample_count} de ${comparison.min_sample_size}) — não use para decidir qual modelo é melhor ainda`
                        }
                      >
                        {m.has_enough_samples
                          ? 'amostra suficiente'
                          : `${m.sample_count}/${comparison.min_sample_size} amostras`}
                      </span>
                    </div>
                    <div className="report-stats">
                      <div className="report-stat">
                        <span className="report-stat-value">{fmt(m.temperature_mae_c, 1, '°C')}</span>
                        <span className="report-stat-label">erro médio de temperatura</span>
                      </div>
                      <div className="report-stat">
                        <span className="report-stat-value">
                          {m.precipitation ? fmt(m.precipitation.bias_mm, 1, 'mm') : '—'}
                        </span>
                        <span className="report-stat-label">viés de chuva</span>
                      </div>
                      <div className="report-stat">
                        <span className="report-stat-value">
                          {m.rain_hit_rate == null ? '—' : `${(m.rain_hit_rate * 100).toFixed(0)}%`}
                        </span>
                        <span className="report-stat-label">acerto chuva sim/não</span>
                      </div>
                      <div className="report-stat">
                        <span className="report-stat-value">{fmt(m.wind_mae_kmh, 1, ' km/h')}</span>
                        <span className="report-stat-label">erro médio de vento</span>
                      </div>
                      <div className="report-stat">
                        <span className="report-stat-value">{fmt(m.brier_score, 2)}</span>
                        <span className="report-stat-label">Brier Score (menor = melhor)</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={onClose}>
                Fechar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
