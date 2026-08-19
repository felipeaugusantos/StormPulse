import type { RiskLevel } from './types'

export const colors = {
  ground: '#0b1120',
  panel: '#111a2e',
  panel2: '#16213a',
  line: '#24324f',
  ink: '#e9eef8',
  inkDim: '#aab7d1',
  inkMute: '#6f7f9e',
  accent: '#4cc2e6',
  green: '#37d39b',
  yellow: '#f2c14e',
  orange: '#f59e5b',
  red: '#ef6d6d',
}

export const LEVEL_COLOR: Record<RiskLevel, string> = {
  green: colors.green,
  yellow: colors.yellow,
  orange: colors.orange,
  red: colors.red,
}

export const LEVEL_LABEL: Record<RiskLevel, string> = {
  green: 'Estável',
  yellow: 'Atento',
  orange: 'Alerta',
  red: 'Perigo',
}
