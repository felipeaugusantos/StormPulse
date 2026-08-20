/** Reverse geocoding (lat/lon → city name) via OpenStreetMap Nominatim.
 *
 * Free, no API key — same OSM ecosystem the base map tiles already come
 * from. Nominatim's usage policy caps at ~1 request/second and asks for
 * low, non-bulk volume, so calls here are serialized through a small queue
 * with a minimum gap between them, and results are cached (rounded to
 * ~1km) so the same point is never looked up twice across poll cycles.
 * Never blocks rendering — callers get `null` immediately and the resolved
 * name later, falling back to raw coordinates on any failure.
 */

const CACHE = new Map<string, string | null>()
const MIN_GAP_MS = 1100

let queue: Promise<void> = Promise.resolve()

function cacheKey(latitude: number, longitude: number): string {
  return `${latitude.toFixed(2)},${longitude.toFixed(2)}`
}

function formatPlace(address: Record<string, string>): string | null {
  const city = address.city ?? address.town ?? address.village ?? address.municipality
  const state = address.state
  if (city && state) return `${city}, ${state}`
  return city ?? state ?? null
}

async function fetchPlaceName(latitude: number, longitude: number): Promise<string | null> {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${latitude}&lon=${longitude}&zoom=10`
    const res = await fetch(url, { headers: { Accept: 'application/json' } })
    if (!res.ok) return null
    const data = await res.json()
    return formatPlace(data.address ?? {})
  } catch {
    return null
  }
}

/** Cached, rate-limited reverse geocode. Returns `null` while unresolved or
 * on failure — callers should fall back to raw coordinates in that case. */
export function reverseGeocodeCity(
  latitude: number,
  longitude: number,
  onResolved: (place: string | null) => void,
): void {
  const key = cacheKey(latitude, longitude)
  if (CACHE.has(key)) {
    onResolved(CACHE.get(key) ?? null)
    return
  }
  queue = queue.then(async () => {
    const place = await fetchPlaceName(latitude, longitude)
    CACHE.set(key, place)
    onResolved(place)
    await new Promise((resolve) => setTimeout(resolve, MIN_GAP_MS))
  })
}
