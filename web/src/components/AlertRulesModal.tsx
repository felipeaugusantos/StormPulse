import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { AlertCondition, AlertConditionInput, AlertMetric, AlertOperator, AlertRule } from '../types'

interface Props {
  locationId: string
  locationName: string
  onClose: () => void
}

const METRIC_LABEL: Record<AlertMetric, string> = {
  rain_mm: 'Chuva (mm)',
  rain_probability_percent: 'Probabilidade de chuva (%)',
  wind_kmh: 'Vento (km/h)',
  temperature_c: 'Temperatura (°C)',
  frost_temperature_c: 'Temperatura mínima / geada (°C)',
  vpd_kpa: 'VPD (kPa)',
  soil_moisture_percent: 'Umidade do solo (%)',
  disease_risk_high: 'Risco de doença alto (1 = sim, 0 = não)',
  lightning_distance_km: 'Distância de raio (km)',
  storm_eta_minutes: 'Chegada da tempestade (min)',
}

const METRICS = Object.keys(METRIC_LABEL) as AlertMetric[]
const OPERATORS: AlertOperator[] = ['>', '>=', '<', '<=', '==']

function emptyCondition(): AlertConditionInput {
  return { metric: 'wind_kmh', operator: '>', threshold: 40, group: 0 }
}

/** Criar e simular regras de alerta personalizadas (Fase 3, ADR-0086) —
 * escopo do formulário: condições em grupos (mesmo grupo = E, grupos
 * diferentes = OU), cooldown, horário silencioso. Simulação nunca envia
 * um alerta real — só mostra se dispararia agora e com quais valores. */
export function AlertRulesModal({ locationId, locationName, onClose }: Props) {
  const [rules, setRules] = useState<AlertRule[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [cooldownMinutes, setCooldownMinutes] = useState(0)
  const [conditions, setConditions] = useState<AlertConditionInput[]>([emptyCondition()])
  const [saving, setSaving] = useState(false)

  const [simulating, setSimulating] = useState<string | null>(null)
  const [simResult, setSimResult] = useState<Record<string, { would_fire: boolean; text: string }>>({})

  function load() {
    setLoading(true)
    setError(null)
    api
      .alertRules(locationId)
      .then((r) => setRules(r))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Não foi possível carregar as regras'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [locationId])

  function updateCondition(index: number, patch: Partial<AlertConditionInput>) {
    setConditions((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)))
  }

  async function submitCreate() {
    if (!name.trim() || conditions.length === 0) return
    setSaving(true)
    setError(null)
    try {
      await api.createAlertRule({
        location_id: locationId,
        name: name.trim(),
        cooldown_minutes: cooldownMinutes,
        conditions,
      })
      setCreating(false)
      setName('')
      setCooldownMinutes(0)
      setConditions([emptyCondition()])
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar a regra')
    } finally {
      setSaving(false)
    }
  }

  async function removeRule(ruleId: string) {
    try {
      await api.deleteAlertRule(ruleId)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível remover a regra')
    }
  }

  async function simulate(rule: AlertRule) {
    setSimulating(rule.id)
    try {
      const result = await api.simulateAlertRule(rule.id)
      const parts = Object.entries(result.snapshot)
        .filter(([, v]) => v != null)
        .map(([k, v]) => `${k}=${v}`)
        .join(', ')
      setSimResult((prev) => ({
        ...prev,
        [rule.id]: {
          would_fire: result.would_fire,
          text: result.would_fire
            ? `Dispararia agora (${parts || 'sem dados'})`
            : `Não dispararia agora (${parts || 'sem dados'})`,
        },
      }))
    } catch (err) {
      setSimResult((prev) => ({
        ...prev,
        [rule.id]: {
          would_fire: false,
          text: err instanceof ApiError ? err.message : 'Falha ao simular',
        },
      }))
    } finally {
      setSimulating(null)
    }
  }

  function describeCondition(c: AlertCondition): string {
    return `${METRIC_LABEL[c.metric as AlertMetric] ?? c.metric} ${c.operator} ${c.threshold}`
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🔔 Alertas personalizados — {locationName}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading && <p className="panel-hint">carregando…</p>}
        {error && <p className="error">⚠️ {error}</p>}

        {rules && (
          <>
            {rules.length === 0 && !creating && (
              <p className="panel-hint">Nenhuma regra personalizada ainda para este talhão.</p>
            )}
            <div className="list" style={{ marginTop: 8 }}>
              {rules.map((rule) => (
                <div className="row" key={rule.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <div className="grow" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <strong>{rule.name}</strong>
                    <div>
                      <button
                        type="button"
                        className="btn ghost small"
                        disabled={simulating === rule.id}
                        onClick={() => simulate(rule)}
                      >
                        {simulating === rule.id ? 'simulando…' : '▶️ simular'}
                      </button>{' '}
                      <button type="button" className="btn ghost small" onClick={() => removeRule(rule.id)}>
                        remover
                      </button>
                    </div>
                  </div>
                  <p className="panel-hint">
                    {rule.conditions.length === 0
                      ? 'sem condições'
                      : rule.conditions
                          .reduce<string[][]>((groups, c) => {
                            groups[c.group] = groups[c.group] ?? []
                            groups[c.group].push(describeCondition(c))
                            return groups
                          }, [])
                          .filter(Boolean)
                          .map((g) => g.join(' E '))
                          .join(' — OU — ')}
                    {rule.cooldown_minutes > 0 && ` · cooldown ${rule.cooldown_minutes}min`}
                  </p>
                  {simResult[rule.id] && (
                    <p className={simResult[rule.id].would_fire ? 'error' : 'panel-hint'}>
                      {simResult[rule.id].would_fire ? '🔥 ' : '✅ '}
                      {simResult[rule.id].text}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {!creating ? (
              <button type="button" className="btn ghost" style={{ marginTop: 12 }} onClick={() => setCreating(true)}>
                + nova regra
              </button>
            ) : (
              <div className="location-create-form" style={{ marginTop: 12 }}>
                <label>Nome da regra</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Vento forte" />

                <label>Cooldown entre avisos (minutos)</label>
                <input
                  type="number"
                  min={0}
                  value={cooldownMinutes}
                  onChange={(e) => setCooldownMinutes(Number(e.target.value))}
                />

                <label>Condições (mesmo grupo = E, grupos diferentes = OU)</label>
                {conditions.map((c, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'center' }}>
                    <select value={c.metric} onChange={(e) => updateCondition(i, { metric: e.target.value as AlertMetric })}>
                      {METRICS.map((m) => (
                        <option key={m} value={m}>
                          {METRIC_LABEL[m]}
                        </option>
                      ))}
                    </select>
                    <select
                      value={c.operator}
                      onChange={(e) => updateCondition(i, { operator: e.target.value as AlertOperator })}
                    >
                      {OPERATORS.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      style={{ width: 90 }}
                      value={c.threshold}
                      onChange={(e) => updateCondition(i, { threshold: Number(e.target.value) })}
                    />
                    <input
                      type="number"
                      title="Grupo (E/OU)"
                      style={{ width: 60 }}
                      min={0}
                      value={c.group ?? 0}
                      onChange={(e) => updateCondition(i, { group: Number(e.target.value) })}
                    />
                    <button
                      type="button"
                      className="btn ghost small"
                      onClick={() => setConditions((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn ghost small"
                  onClick={() => setConditions((prev) => [...prev, emptyCondition()])}
                >
                  + condição
                </button>

                <div className="location-create-actions">
                  <button type="button" className="btn" disabled={saving} onClick={submitCreate}>
                    {saving ? 'Salvando…' : 'Criar regra'}
                  </button>
                  <button type="button" className="btn ghost" disabled={saving} onClick={() => setCreating(false)}>
                    Cancelar
                  </button>
                </div>
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
