/** Deterministic color per crop name — used to color talhão polygon
 * outlines on the map so different cultures are visually distinct
 * (FASE 27, ADR-0024). A small fixed palette covers the common Brazilian
 * row crops; anything else falls back to a stable hash-based color so the
 * same crop name always gets the same color, even if it's not in the
 * fixed list. */

const FIXED_PALETTE: Record<string, string> = {
  soja: '#f2c14e',
  milho: '#f5d76e',
  'cana-de-açúcar': '#37d39b',
  cana: '#37d39b',
  café: '#8b5a2b',
  algodão: '#e9eef8',
  trigo: '#e0a458',
  arroz: '#4cc2e6',
  pastagem: '#7fb069',
  feijão: '#a26769',
}

const FALLBACK_PALETTE = [
  '#ef6d6d',
  '#a78bfa',
  '#f59e5b',
  '#4cc2e6',
  '#37d39b',
  '#f2c14e',
  '#fb7185',
  '#60a5fa',
]

// Mobile has no native color-picker input (unlike the web's
// `<input type="color">`) — this is the preset palette shown for the user
// to tap-select a manual override from.
export const COLOR_PALETTE = [...new Set([...Object.values(FIXED_PALETTE), ...FALLBACK_PALETTE])]

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i++) {
    hash = (hash << 5) - hash + value.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

/** Color for a crop name, or a neutral gray when there's no crop set. */
export function cropColor(crop: string | null | undefined): string {
  if (!crop) return '#6f7f9e'
  const key = crop.trim().toLowerCase()
  if (FIXED_PALETTE[key]) return FIXED_PALETTE[key]
  return FALLBACK_PALETTE[hashString(key) % FALLBACK_PALETTE.length]
}
