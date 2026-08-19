import { useEffect, useRef, useState } from 'react'
import { searchPlaces, type GeoResult } from '../api/openMeteo'
import { placeLabel } from '../lib/format'

interface Props {
  onSelect: (place: GeoResult) => void
}

export function SearchBar({ onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GeoResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  // Debounced geocoding search.
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults([])
      return
    }
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const r = await searchPlaces(q)
        setResults(r)
        setOpen(true)
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  // Close dropdown on outside click.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  function choose(place: GeoResult) {
    onSelect(place)
    setQuery(place.name)
    setOpen(false)
  }

  function useMyLocation() {
    if (!navigator.geolocation) return
    setLoading(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLoading(false)
        choose({
          id: -1,
          name: 'Minha localização',
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          country: '',
          countryCode: '',
          timezone: 'auto',
        })
      },
      () => setLoading(false),
      { timeout: 8000 },
    )
  }

  return (
    <div className="search" ref={boxRef}>
      <div className="search-row">
        <span className="search-icon" aria-hidden>🔍</span>
        <input
          className="search-input"
          type="text"
          value={query}
          placeholder="Buscar cidade…"
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          aria-label="Buscar cidade"
        />
        <button
          className="loc-btn"
          onClick={useMyLocation}
          title="Usar minha localização"
          aria-label="Usar minha localização"
        >
          📍
        </button>
      </div>

      {open && (results.length > 0 || loading) && (
        <ul className="search-results" role="listbox">
          {loading && <li className="search-hint">Buscando…</li>}
          {results.map((r) => (
            <li key={`${r.id}-${r.latitude}`}>
              <button className="search-result" onClick={() => choose(r)} role="option">
                <span className="result-name">{r.name}</span>
                <span className="result-meta">{placeLabel('', r.admin1, r.country)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
