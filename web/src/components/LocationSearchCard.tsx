import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import { cropColor } from '../cropColors'
import { reverseGeocodeCity, searchCity } from '../geocode'
import type { CitySearchResult, LocationItem } from '../types'

const SEARCH_DEBOUNCE_MS = 400

interface Props {
  locations: LocationItem[]
  selectedLocationId: string | null
  onSelectLocation: (id: string) => void
  onLocationCreated: (location: LocationItem) => void
  onLocationUpdated: (location: LocationItem) => void
  onLocationDeleted: (id: string) => void
  /** Kicks off polygon drawing on the map (FASE 27, ADR-0024); `onComplete`
   * fires with a GeoJSON Polygon JSON string once the user finishes. */
  onStartDrawBoundary: (onComplete: (boundaryGeojson: string) => void) => void
  /** Kicks off click-to-place-a-point mode on the map — e.g. marking the
   * street where someone lives, when there's no city-level match to search
   * for. `onPicked` fires once with the clicked coordinate. */
  onStartPickLocation: (onPicked: (latitude: number, longitude: number) => void) => void
  /** Talhão *creation* (the "+ talhão" button and its form) only makes
   * sense in the Agro context — a plot is an agro concept (cultura,
   * contorno de plantio), not something the storm-tracking tab has any
   * use for. Already-created plots still show up under their farm in
   * both tabs; only the entry points to *creating* a new one are gated. */
  plotCreationEnabled: boolean
}

export function LocationSearchCard({
  locations,
  selectedLocationId,
  onSelectLocation,
  onLocationCreated,
  onLocationUpdated,
  onLocationDeleted,
  onStartDrawBoundary,
  onStartPickLocation,
  plotCreationEnabled,
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
  const [plotBoundaryGeojson, setPlotBoundaryGeojson] = useState<string | null>(null)
  const [plotColor, setPlotColor] = useState(cropColor(null))
  const [creatingPlot, setCreatingPlot] = useState(false)
  const [updatingColorFor, setUpdatingColorFor] = useState<string | null>(null)

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

  async function updatePlotColor(plot: LocationItem, color: string) {
    setUpdatingColorFor(plot.id)
    try {
      const updated = await api.updateLocation(plot.id, { color })
      onLocationUpdated(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível atualizar a cor')
    } finally {
      setUpdatingColorFor(null)
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
    setPlotBoundaryGeojson(null)
    setPlotColor(cropColor(null))
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
        boundary_geojson: plotBoundaryGeojson ?? undefined,
        color: plotColor,
      })
      onLocationCreated(created)
      onSelectLocation(created.id)
      setAddingPlotFor(null)
      setPlotBoundaryGeojson(null)
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
            <button
              type="button"
              className="btn ghost small"
              onClick={() =>
                onStartPickLocation((latitude, longitude) => {
                  reverseGeocodeCity(latitude, longitude, (place) => {
                    pick({
                      label: place ?? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`,
                      latitude,
                      longitude,
                    })
                  })
                })
              }
              title="Marcar um ponto no mapa"
            >
              🖊️ marcar no mapa
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
                  {plotCreationEnabled && (
                    <button
                      className="btn ghost small"
                      onClick={(e) => {
                        e.stopPropagation()
                        startAddingPlot(farm)
                      }}
                    >
                      + talhão
                    </button>
                  )}
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
                    <input
                      type="color"
                      className="color-swatch-input"
                      value={plot.color ?? cropColor(plot.crop)}
                      disabled={updatingColorFor === plot.id}
                      title="Cor do talhão no mapa"
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => updatePlotColor(plot, e.target.value)}
                    />
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

                {plotCreationEnabled && addingPlotFor === farm.id && (
                  <div className="location-create-form plot-create-form">
                    <label>Nome do talhão</label>
                    <input value={plotName} onChange={(e) => setPlotName(e.target.value)} />
                    <label>Cultura (opcional)</label>
                    <input
                      value={plotCrop}
                      onChange={(e) => {
                        setPlotCrop(e.target.value)
                        setPlotColor(cropColor(e.target.value))
                      }}
                      placeholder="soja, milho, café…"
                    />
                    <label>Cor no mapa</label>
                    <input
                      type="color"
                      className="color-swatch-input"
                      value={plotColor}
                      onChange={(e) => setPlotColor(e.target.value)}
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
                    <button
                      type="button"
                      className="btn ghost small"
                      onClick={() =>
                        onStartDrawBoundary((geojson) => setPlotBoundaryGeojson(geojson))
                      }
                    >
                      {plotBoundaryGeojson ? '✓ contorno desenhado — redesenhar' : '🖊️ Desenhar contorno no mapa'}
                    </button>
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
