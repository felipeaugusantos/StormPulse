/** CAPE classification — ported from `web/src/storm.ts` (FASE 26,
 * ADR-0023). Thresholds match REDEMET's own 4-tier classification
 * (Fraca/Moderada/Forte/Extremo), an industry-standard scale. The web
 * version's storm-ETA helpers aren't ported here — the mobile home screen
 * already gets `storm_distance_km`/`eta_minutes` straight from the backend
 * (`StormRisk`), it doesn't need its own satellite-watch ETA projection. */

export type CapeLevel = 'weak' | 'moderate' | 'strong' | 'extreme'

export function classifyCape(capeJkg: number): CapeLevel {
  if (capeJkg < 1000) return 'weak'
  if (capeJkg < 2500) return 'moderate'
  if (capeJkg < 4000) return 'strong'
  return 'extreme'
}
