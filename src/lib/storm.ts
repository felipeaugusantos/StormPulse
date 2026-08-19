// The "pulse" of StormPulse: turn raw forecast numbers into a single
// storm-risk assessment plus human-readable alerts for the next 24h.

import type { Forecast } from '../api/openMeteo'

export type RiskLevel = 'calm' | 'watch' | 'warning' | 'severe'

export interface StormAssessment {
  level: RiskLevel
  score: number // 0-100
  title: string
  summary: string
  alerts: string[]
}

const LEVEL_META: Record<RiskLevel, { title: string }> = {
  calm: { title: 'Tempo estável' },
  watch: { title: 'Fique atento' },
  warning: { title: 'Alerta de tempo severo' },
  severe: { title: 'Perigo — tempo severo' },
}

// Thunderstorm WMO codes.
const STORM_CODES = new Set([82, 95, 96, 99])

export function assessStorm(forecast: Forecast): StormAssessment {
  const { current, hourly } = forecast
  const alerts: string[] = []
  let score = 0

  const maxGust = Math.max(current.windGusts, ...hourly.map((h) => h.windGusts))
  const maxPrecipProb = Math.max(...hourly.map((h) => h.precipitationProbability))
  const totalPrecip = hourly.reduce((s, h) => s + h.precipitation, 0)
  const stormHours = hourly.filter((h) => STORM_CODES.has(h.weatherCode)).length

  // Wind gusts (km/h).
  if (maxGust >= 90) {
    score += 45
    alerts.push(`Rajadas de vento de até ${Math.round(maxGust)} km/h previstas.`)
  } else if (maxGust >= 60) {
    score += 28
    alerts.push(`Vento forte: rajadas de até ${Math.round(maxGust)} km/h.`)
  } else if (maxGust >= 40) {
    score += 12
  }

  // Thunderstorm activity.
  if (stormHours > 0 || STORM_CODES.has(current.weatherCode)) {
    score += Math.min(35, 12 + stormHours * 4)
    alerts.push(
      stormHours > 0
        ? `Tempestades previstas em ${stormHours}h das próximas 24h.`
        : 'Condições de tempestade no momento.',
    )
  }

  // Precipitation.
  if (totalPrecip >= 40) {
    score += 25
    alerts.push(`Chuva acumulada de ${totalPrecip.toFixed(0)} mm em 24h — risco de alagamento.`)
  } else if (totalPrecip >= 15) {
    score += 12
    alerts.push(`Chuva significativa: ${totalPrecip.toFixed(0)} mm nas próximas 24h.`)
  }

  if (maxPrecipProb >= 80 && totalPrecip < 15) {
    score += 6
    alerts.push(`Alta probabilidade de chuva (${maxPrecipProb}%).`)
  }

  score = Math.min(100, score)

  let level: RiskLevel = 'calm'
  if (score >= 65) level = 'severe'
  else if (score >= 40) level = 'warning'
  else if (score >= 18) level = 'watch'

  const summary =
    level === 'calm'
      ? 'Nenhuma condição severa detectada nas próximas 24 horas.'
      : `${alerts.length} fator${alerts.length > 1 ? 'es' : ''} de risco nas próximas 24 horas.`

  if (level === 'calm' && alerts.length === 0) {
    alerts.push('Céu comportado. Bom momento para atividades ao ar livre.')
  }

  return {
    level,
    score,
    title: LEVEL_META[level].title,
    summary,
    alerts,
  }
}
