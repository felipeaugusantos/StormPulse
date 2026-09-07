import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import { alertEventLabel, riskLevelLabel, timeAgo, timeUntil } from '../format'
import type { RiskDigest } from '../types'

interface Props {
  locationId: string
  locationName: string
  onClose: () => void
}

/** Painel "Risco consolidado" (Fase 3-A, ADR-0087) — lê o /risk-digest,
 * que agrega sinais já calculados (nunca recalcula nada). Cada linha é
 * independentemente ausente quando o sinal não se aplica a este local ou
 * ainda não foi calculado — nunca um placeholder de "zero". */
export function RiskDigestModal({ locationId, locationName, onClose }: Props) {
  const [digest, setDigest] = useState<RiskDigest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .riskDigest(locationId)
      .then((d) => {
        if (!cancelled) setDigest(d)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Não foi possível carregar o risco consolidado')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [locationId])

  const hasAnySignal =
    digest != null &&
    (digest.storm != null ||
      digest.ndvi != null ||
      digest.deforestation != null ||
      digest.frost_last_alert != null ||
      digest.dry_spell_last_alert != null ||
      digest.soil_moisture != null)

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🧭 Risco consolidado — {locationName}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading && <p className="panel-hint">carregando…</p>}
        {error && <p className="error">⚠️ {error}</p>}

        {digest && !loading && (
          <>
            {!hasAnySignal && (
              <p className="panel-hint">
                Nenhum sinal calculado ainda para este local — os painéis vão preencher aqui
                conforme os ciclos de monitoramento rodarem.
              </p>
            )}

            <div className="list" style={{ marginTop: 8 }}>
              {digest.storm && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>⛈️ Tempestade — {riskLevelLabel(digest.storm.severity)}</strong>
                  <p className="panel-hint">
                    {digest.storm.eta_minutes != null &&
                      `chega ${timeUntil(digest.storm.eta_minutes)} · `}
                    {digest.storm.storm_distance_km != null &&
                      `${digest.storm.storm_distance_km.toFixed(0)} km · `}
                    calculado {timeAgo(digest.storm.computed_at)}
                    {digest.storm.is_mock && ' · dado simulado'}
                  </p>
                </div>
              )}

              {digest.ndvi && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>🌱 Vegetação (NDVI) — {digest.ndvi.ndvi_mean?.toFixed(2) ?? '—'}</strong>
                  <p className="panel-hint">
                    observado {timeAgo(digest.ndvi.observed_at)}
                    {digest.ndvi.is_mock && ' · dado simulado'}
                  </p>
                </div>
              )}

              {digest.deforestation && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>
                    🌳 Desmatamento —{' '}
                    {digest.deforestation.alerts.length > 0
                      ? `${digest.deforestation.alerts.length} alerta(s)`
                      : 'nenhum alerta'}
                  </strong>
                  <p className="panel-hint">
                    fontes verificadas: {digest.deforestation.checked_sources.join(', ') || '—'}
                    {digest.deforestation.last_checked_at &&
                      ` · última checagem ${timeAgo(digest.deforestation.last_checked_at)}`}
                  </p>
                </div>
              )}

              {digest.frost_last_alert && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>❄️ {alertEventLabel('frost_warning')} — último alerta</strong>
                  <p className="panel-hint">
                    {digest.frost_last_alert.title} · {timeAgo(digest.frost_last_alert.occurred_at)}
                  </p>
                  <p className="panel-hint" style={{ fontStyle: 'italic' }}>
                    histórico, não é o risco agora — veja a aba Agro para a previsão atual.
                  </p>
                </div>
              )}

              {digest.dry_spell_last_alert && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>☀️ {alertEventLabel('dry_spell_warning')} — último alerta</strong>
                  <p className="panel-hint">
                    {digest.dry_spell_last_alert.title} ·{' '}
                    {timeAgo(digest.dry_spell_last_alert.occurred_at)}
                  </p>
                  <p className="panel-hint" style={{ fontStyle: 'italic' }}>
                    histórico, não é o risco agora — veja a aba Agro para a previsão atual.
                  </p>
                </div>
              )}

              {digest.soil_moisture && (
                <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <strong>💧 Umidade do solo — {digest.soil_moisture.root_zone_wetness_percent.toFixed(0)}%</strong>
                  <p className="panel-hint">
                    estimativa regional, {digest.soil_moisture.observed_at}
                    {digest.soil_moisture.is_mock && ' · dado simulado'}
                  </p>
                </div>
              )}
            </div>
          </>
        )}

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  )
}
