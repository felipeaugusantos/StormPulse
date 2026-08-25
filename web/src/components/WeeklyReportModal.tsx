import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import { classifyNdvi, NDVI_LABEL } from '../agro'
import type { WeeklyReport } from '../types'

interface Props {
  locationId: string
  locationName: string
  onClose: () => void
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

/** Weekly report for a single talhão (FASE 32) — last 7 full days of
 * rainfall, agro alerts and NDVI, meant to be printed/shown to an
 * agronomist or bank. `@media print` in index.css hides everything on the
 * page except `.report-print` when the user hits "Imprimir". */
export function WeeklyReportModal({ locationId, locationName, onClose }: Props) {
  const [report, setReport] = useState<WeeklyReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .weeklyReport(locationId)
      .then((r) => {
        if (!cancelled) setReport(r)
      })
      .catch((err) => {
        if (cancelled) return
        setError(
          err instanceof ApiError ? err.message : 'Não foi possível carregar o relatório',
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
      <div className="modal-card report-print" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header no-print">
          <h2>📄 Relatório semanal — {locationName}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading && <p className="panel-hint">carregando…</p>}
        {error && <p className="error">⚠️ {error}</p>}

        {report && (
          <>
            <p className="report-period">
              Período: {formatDate(report.period_start)} a {formatDate(report.period_end)}
            </p>

            <div className="report-stats">
              <div className="report-stat">
                <span className="report-stat-value">{report.rainfall_total_mm.toFixed(1)}mm</span>
                <span className="report-stat-label">chuva acumulada</span>
              </div>
              <div className="report-stat">
                <span className="report-stat-value">{report.dry_days_count}/7</span>
                <span className="report-stat-label">dias secos</span>
              </div>
              {report.crop && (
                <div className="report-stat">
                  <span className="report-stat-value">{report.crop}</span>
                  <span className="report-stat-label">cultura</span>
                </div>
              )}
            </div>

            <h3>Alertas no período</h3>
            {report.alerts.length === 0 ? (
              <p className="panel-hint">Nenhum alerta de geada ou seca no período.</p>
            ) : (
              <ul className="report-list">
                {report.alerts.map((a) => (
                  <li key={a.id}>
                    <strong>{formatDate(a.created_at)}</strong> — {a.title}: {a.message}
                  </li>
                ))}
              </ul>
            )}

            <h3>NDVI no período</h3>
            {report.ndvi_readings.length === 0 ? (
              <p className="panel-hint">Nenhuma leitura de NDVI no período.</p>
            ) : (
              <ul className="report-list">
                {report.ndvi_readings.map((n, i) => (
                  <li key={i}>
                    <strong>{formatDate(n.observed_at)}</strong> — NDVI {n.ndvi_mean.toFixed(2)} —{' '}
                    {NDVI_LABEL[classifyNdvi(n.ndvi_mean)]}
                    {n.is_mock && ' (simulado)'}
                  </li>
                ))}
              </ul>
            )}

            <p className="report-generated no-print">
              Gerado em {new Date(report.generated_at).toLocaleString('pt-BR')}
            </p>

            <div className="modal-actions no-print">
              <button type="button" className="btn" onClick={() => window.print()}>
                🖨️ Imprimir / Salvar PDF
              </button>
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
