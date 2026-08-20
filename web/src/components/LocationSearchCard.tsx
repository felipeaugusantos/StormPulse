import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import { reverseGeocodeCity, searchCity } from '../geocode'
import type { CitySearchResult, LocationItem } from '../types'

const SEARCH_DEBOUNCE_MS = 400

interface Props {
  locations: LocationItem[]
  selectedLocationId: string | null
  onSelectLocation: (id: string) => void
  onLocationCreated: (location: LocationItem) => void
  onLocationDeleted: (id: string) => void
}

export function LocationSearchCard({
  locations,
  selectedLocationId,
  onSelectLocation,
  onLocationCreated,
  onLocationDeleted,
}: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CitySearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<CitySearchResult | null>(null)
  const [name, setName] = useState('')
  const [radiusKm, setRadiusKm] = useState(50)
  const [creating, setCreating] = useState(false)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      const found = await searchCity(query)
      setResults(found)
      setSearching(false)
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  function useMyLocation() {
    if (!navigator.geolocation) {
      setError('Geolocalização não disponível neste navegador')
      return
    }
    setLocating(true)
    setError(null)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        reverseGeocodeCity(latitude, longitude, (place) => {
          setLocating(false)
          pick({ label: place ?? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`, latitude, longitude })
        })
      },
      () => {
        setLocating(false)
        setError('Não foi possível obter sua localização — verifique a permissão do navegador')
      },
      { timeout: 10_000 },
    )
  }

  function pick(result: CitySearchResult) {
    setPicked(result)
    setResults([])
    setQuery('')
    setName(result.label.split(',')[0] ?? result.label)
    setRadiusKm(50)
  }

  async function createLocation() {
    if (!picked) return
    setCreating(true)
    setError(null)
    try {
      const created = await api.createLocation({
        name: name.trim() || picked.label.split(',')[0] || 'Local',
        latitude: picked.latitude,
        longitude: picked.longitude,
        radius_km: radiusKm,
      })
      onLocationCreated(created)
      onSelectLocation(created.id)
      setPicked(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar o local')
    } finally {
      setCreating(false)
    }
  }

  async function removeLocation(id: string) {
    try {
      await api.deleteLocation(id)
      onLocationDeleted(id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível remover o local')
    }
  }

  return (
    <section className="panel">
      <h2>📍 Locais monitorados</h2>

      {picked ? (
        <div className="location-create-form">
          <label>Nome</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <label>Raio (km)</label>
          <input
            type="number"
            min={1}
            max={500}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
          />
          <div className="location-create-actions">
            <button className="btn" disabled={creating} onClick={createLocation}>
              {creating ? 'Adicionando…' : 'Adicionar'}
            </button>
            <button className="btn ghost" onClick={() => setPicked(null)} disabled={creating}>
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="location-search-row">
            <input
              placeholder="Buscar cidade (ex: Ribeirão Preto)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button
              type="button"
              className="btn ghost small"
              onClick={useMyLocation}
              disabled={locating}
              title="Usar minha localização"
            >
              {locating ? '…' : '📍 usar minha localização'}
            </button>
          </div>
          {searching && <p className="panel-hint">buscando…</p>}
          {results.length > 0 && (
            <div className="list search-results">
              {results.map((r) => (
                <div className="row clickable" key={`${r.latitude},${r.longitude}`} onClick={() => pick(r)}>
                  <span className="grow">{r.label}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {error && <p className="error">⚠️ {error}</p>}

      <div className="list" style={{ marginTop: 12 }}>
        {locations.length === 0 && <p className="empty">Nenhum local cadastrado ainda.</p>}
        {locations.map((l) => (
          <div
            className={`row clickable ${selectedLocationId === l.id ? 'selected' : ''}`}
            key={l.id}
            onClick={() => onSelectLocation(l.id)}
          >
            <div className="grow">
              <div>{l.name}</div>
              <div className="sub">
                {l.kind} · raio {l.radius_km} km
              </div>
            </div>
            <button
              className="btn ghost small"
              onClick={(e) => {
                e.stopPropagation()
                removeLocation(l.id)
              }}
            >
              remover
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
