import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import type {
  GeoJSONSource,
  ImageSource,
  LngLatBoundsLike,
  StyleSpecification,
} from 'maplibre-gl'
import { satelliteImagePngUrl } from '../api'
import type {
  ConvectiveWatch,
  LightningStrike,
  LocationItem,
  SatelliteImageMeta,
  StormCell,
} from '../types'

interface Props {
  storms: StormCell[]
  locations: LocationItem[]
  satelliteWatches?: ConvectiveWatch[]
  satelliteImage?: SatelliteImageMeta | null
  lightning?: LightningStrike[]
}

export interface StormMapHandle {
  /** Centers and zooms the map on a point — e.g. clicking a satellite watch row. */
  flyTo(latitude: number, longitude: number): void
}

const SATELLITE_WATCH_COLOR = '#a78bfa'
const LIGHTNING_COLOR = '#fde047'

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

function satelliteWatchesGeoJSON(watches: ConvectiveWatch[]) {
  return {
    type: 'FeatureCollection' as const,
    features: watches.map((w) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [w.longitude, w.latitude] },
      properties: { id: w.id },
    })),
  }
}

function lightningGeoJSON(strikes: LightningStrike[]) {
  return {
    type: 'FeatureCollection' as const,
    features: strikes.map((s) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [s.longitude, s.latitude] },
      properties: { id: s.id },
    })),
  }
}

function imageCoordinates(
  bbox: [number, number, number, number],
): [[number, number], [number, number], [number, number], [number, number]] {
  const [lonMin, latMin, lonMax, latMax] = bbox
  // MapLibre `image` source coordinates go clockwise from the top-left.
  return [
    [lonMin, latMax],
    [lonMax, latMax],
    [lonMax, latMin],
    [lonMin, latMin],
  ]
}

export const StormMap = forwardRef<StormMapHandle, Props>(function StormMap(
  { storms, locations, satelliteWatches = [], satelliteImage = null, lightning = [] },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const readyRef = useRef(false)

  useImperativeHandle(ref, () => ({
    flyTo(latitude: number, longitude: number) {
      mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 9, duration: 600 })
    },
  }))

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
      map.addSource('satellite-watches', { type: 'geojson', data: satelliteWatchesGeoJSON([]) })
      // Satellite watches under storm cells: a precursor signal, drawn
      // "behind" confirmed cells rather than competing visually with them.
      map.addLayer({
        id: 'satellite-watches',
        type: 'circle',
        source: 'satellite-watches',
        paint: {
          'circle-radius': 12,
          'circle-color': SATELLITE_WATCH_COLOR,
          'circle-opacity': 0.25,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': SATELLITE_WATCH_COLOR,
        },
      })
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
      map.addSource('lightning', { type: 'geojson', data: lightningGeoJSON([]) })
      // On top of everything — the most immediate, time-sensitive signal
      // on the map (API-REDEMET STSC, FASE 23).
      map.addLayer({
        id: 'lightning',
        type: 'circle',
        source: 'lightning',
        paint: {
          'circle-radius': 3,
          'circle-color': LIGHTNING_COLOR,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#78350f',
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
      const watches = map.getSource('satellite-watches') as GeoJSONSource | undefined
      const strikes = map.getSource('lightning') as GeoJSONSource | undefined
      if (!cells || !locs || !watches || !strikes) return
      cells.setData(cellsGeoJSON(storms))
      locs.setData(locationsGeoJSON(locations))
      watches.setData(satelliteWatchesGeoJSON(satelliteWatches))
      strikes.setData(lightningGeoJSON(lightning))

      if (satelliteImage) {
        const url = satelliteImagePngUrl(satelliteImage.captured_at)
        const coordinates = imageCoordinates(satelliteImage.bbox)
        const existing = map.getSource('satellite-image') as ImageSource | undefined
        if (existing) {
          existing.updateImage({ url, coordinates })
        } else {
          map.addSource('satellite-image', { type: 'image', url, coordinates })
          // Below satellite-watches (a raster frame behind every point layer,
          // right above the OSM basemap) so it never competes with points.
          map.addLayer(
            {
              id: 'satellite-image',
              type: 'raster',
              source: 'satellite-image',
              paint: { 'raster-opacity': 0.55 },
            },
            'satellite-watches',
          )
        }
        if (map.getLayer('satellite-image')) {
          map.setLayoutProperty('satellite-image', 'visibility', 'visible')
        }
      } else if (map.getLayer('satellite-image')) {
        map.setLayoutProperty('satellite-image', 'visibility', 'none')
      }

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
  }, [storms, locations, satelliteWatches, satelliteImage, lightning])

  return <div className="map" ref={containerRef} />
})
