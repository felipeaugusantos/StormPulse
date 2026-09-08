/** Shared time-formatting helpers (Fase 4, ADR-0088) — mobile previously
 * formatted every date/duration inline per screen. This is the first
 * shared formatter file on the mobile side, mirroring web/src/format.ts's
 * `timeUntil` so storm ETA, frost days and ZARC windows all read the same
 * way across the app. */

/** "em 5 min" / "em ~2 h" / "em 3 dias" — never claims more precision
 * than the source actually has. Each signal keeps its own time unit
 * internally (storm ETA in minutes, frost/ZARC in days); only the
 * presentation is unified. */
export function timeUntil(minutes: number): string {
  const rounded = Math.max(0, Math.round(minutes))
  if (rounded < 1) return 'a qualquer momento'
  if (rounded < 60) return `em ${rounded} min`
  const hours = Math.round(rounded / 60)
  if (hours < 24) return `em ~${hours} h`
  const days = Math.round(rounded / (60 * 24))
  return days === 1 ? 'em 1 dia' : `em ${days} dias`
}

/** "há 3 min" / "há 2 h" — the past-facing counterpart to `timeUntil`,
 * same rounding convention, ported from web/src/format.ts (Fase 6,
 * ADR-0090 — the Caderno de Campo timeline needed it on mobile too). */
export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.max(0, Math.round(diffMs / 60_000))
  if (minutes < 1) return 'agora'
  if (minutes < 60) return `há ${minutes} min`
  const hours = Math.round(minutes / 60)
  return `há ${hours} h`
}
