// Small formatting helpers shared across components.

export function windDirectionLabel(deg: number): string {
  const dirs = ['N', 'NE', 'L', 'SE', 'S', 'SO', 'O', 'NO']
  return dirs[Math.round(deg / 45) % 8]
}

export function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatWeekday(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', { weekday: 'short' })
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(ts: number): string {
  const secs = Math.round((Date.now() - ts) / 1000)
  if (secs < 60) return 'agora mesmo'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `há ${mins} min`
  const hours = Math.round(mins / 60)
  return `há ${hours} h`
}

export function placeLabel(name: string, admin1?: string, country?: string): string {
  return [name, admin1, country].filter(Boolean).join(', ')
}
