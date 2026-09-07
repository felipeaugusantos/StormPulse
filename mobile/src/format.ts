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
