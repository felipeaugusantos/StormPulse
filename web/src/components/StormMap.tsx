import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import type {
  GeoJSONSource,
  LngLatBoundsLike,
  StyleSpecification,
} from 'maplibre-gl'
import type { LocationItem, StormCell } from '../types'

interface Props {
  storms: StormCell[]
  locations: LocationItem[]
}

const SEVERITY_COLOR: Record<string, string> = {
  weak: '#37d39b',
  moderate: '#f2c14e',
  strong: '#f59e5b',
  severe: '#ef6d6d',
}

const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

function cellsGeoJSON(storms: StormCell[]) {
  return {
    type: 'FeatureCollection' as const,
    features: storms.map((s) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [s.longitude, s.latitude] },
      properties: { color: SEVERITY_COLOR[s.severity] ?? '#4cc2e6', severity: s.severity },
    })),
  }
}

function locationsGeoJSON(locations: LocationItem[]) {
  return {
    type: 'FeatureCollection' as const,
    features: locations.map((l) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [l.longitude, l.latitude] },
      properties: { name: l.name },
    })),
  }
}

export function StormMap({ storms, locations }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const readyRef = useRef(false)

  // Initialize the map once.
  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: [-46.63, -23.55],
      zoom: 6,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    mapRef.current = map

    map.on('load', () => {
      map.addSource('cells', { type: 'geojson', data: cellsGeoJSON([]) })
      map.addSource('locations', { type: 'geojson', data: locationsGeoJSON([]) })
      map.addLayer({
        id: 'cells',
        type: 'circle',
        source: 'cells',
        paint: {
          'circle-radius': 9,
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.75,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#0b1120',
        },
      })
      map.addLayer({
        id: 'locations',
        type: 'circle',
        source: 'locations',
        paint: {
          'circle-radius': 6,
          'circle-color': '#4cc2e6',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#0b1120',
        },
      })
      readyRef.current = true
    })

    return () => {
      map.remove()
      mapRef.current = null
      readyRef.current = false
    }
  }, [])

  // Push data updates into the map sources.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const apply = () => {
      const cells = map.getSource('cells') as GeoJSONSource | undefined
      const locs = map.getSource('locations') as GeoJSONSource | undefined
      if (!cells || !locs) return
      cells.setData(cellsGeoJSON(storms))
      locs.setData(locationsGeoJSON(locations))

      const points = [
        ...storms.map((s) => [s.longitude, s.latitude] as [number, number]),
        ...locations.map((l) => [l.longitude, l.latitude] as [number, number]),
      ]
      if (points.length > 0) {
        const bounds = points.reduce(
          (b, p) => b.extend(p),
          new maplibregl.LngLatBounds(points[0], points[0]),
        )
        map.fitBounds(bounds as LngLatBoundsLike, { padding: 60, maxZoom: 9, duration: 400 })
      }
    }

    if (readyRef.current) apply()
    else map.once('load', apply)
  }, [storms, locations])

  return <div className="map" ref={containerRef} />
}
