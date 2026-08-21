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

  // Talhão support (FASE 26): plot creation is a small inline form under
  // its parent farm, not the city-search flow above — a plot's coordinate
  // starts at the farm's own (editable), it's never a new place someone
  // needs to search for.
  const [addingPlotFor, setAddingPlotFor] = useState<string | null>(null)
  const [plotName, setPlotName] = useState('')
  const [plotCrop, setPlotCrop] = useState('')
  const [plotLatitude, setPlotLatitude] = useState(0)
  const [plotLongitude, setPlotLongitude] = useState(0)
  const [creatingPlot, setCreatingPlot] = useState(false)

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

  function startAddingPlot(farm: LocationItem) {
    setAddingPlotFor(farm.id)
    setPlotName('')
    setPlotCrop('')
    setPlotLatitude(farm.latitude)
    setPlotLongitude(farm.longitude)
    setError(null)
  }

  async function createPlot(farmId: string) {
    setCreatingPlot(true)
    setError(null)
    try {
      const created = await api.createLocation({
        name: plotName.trim() || 'Talhão',
        latitude: plotLatitude,
        longitude: plotLongitude,
        parent_location_id: farmId,
        crop: plotCrop.trim() || undefined,
      })
      onLocationCreated(created)
      onSelectLocation(created.id)
      setAddingPlotFor(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar o talhão')
    } finally {
      setCreatingPlot(false)
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
        {locations
          .filter((l) => l.parent_location_id == null)
          .map((farm) => {
            const plots = locations.filter((l) => l.parent_location_id === farm.id)
            return (
              <div key={farm.id}>
                <div
                  className={`row clickable ${selectedLocationId === farm.id ? 'selected' : ''}`}
                  onClick={() => onSelectLocation(farm.id)}
                >
                  <div className="grow">
                    <div>{farm.name}</div>
                    <div className="sub">
                      {farm.kind} · raio {farm.radius_km} km
                    </div>
                  </div>
                  <button
                    className="btn ghost small"
                    onClick={(e) => {
                      e.stopPropagation()
                      startAddingPlot(farm)
                    }}
                  >
                    + talhão
                  </button>
                  <button
                    className="btn ghost small"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeLocation(farm.id)
                    }}
                  >
                    remover
                  </button>
                </div>

                {plots.map((plot) => (
                  <div
                    className={`row clickable plot-row ${selectedLocationId === plot.id ? 'selected' : ''}`}
                    key={plot.id}
                    onClick={() => onSelectLocation(plot.id)}
                  >
                    <div className="grow">
                      <div>🌱 {plot.name}</div>
                      <div className="sub">{plot.crop ?? 'cultura não informada'}</div>
                    </div>
                    <button
                      className="btn ghost small"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeLocation(plot.id)
                      }}
                    >
                      remover
                    </button>
                  </div>
                ))}

                {addingPlotFor === farm.id && (
                  <div className="location-create-form plot-create-form">
                    <label>Nome do talhão</label>
                    <input value={plotName} onChange={(e) => setPlotName(e.target.value)} />
                    <label>Cultura (opcional)</label>
                    <input
                      value={plotCrop}
                      onChange={(e) => setPlotCrop(e.target.value)}
                      placeholder="soja, milho, café…"
                    />
                    <label>Latitude</label>
                    <input
                      type="number"
                      step="any"
                      value={plotLatitude}
                      onChange={(e) => setPlotLatitude(Number(e.target.value))}
                    />
                    <label>Longitude</label>
                    <input
                      type="number"
                      step="any"
                      value={plotLongitude}
                      onChange={(e) => setPlotLongitude(Number(e.target.value))}
                    />
                    <div className="location-create-actions">
                      <button
                        className="btn"
                        disabled={creatingPlot}
                        onClick={() => createPlot(farm.id)}
                      >
                        {creatingPlot ? 'Adicionando…' : 'Adicionar talhão'}
                      </button>
                      <button
                        className="btn ghost"
                        onClick={() => setAddingPlotFor(null)}
                        disabled={creatingPlot}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
      </div>
    </section>
  )
}
