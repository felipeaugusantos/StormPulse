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

export interface PlotBoundary {
  id: string
  name: string
  color: string
  /** GeoJSON Polygon `coordinates` — an array of linear rings, each ring an
   * array of [lng, lat] pairs. */
  coordinates: [number, number][][]
}

interface Props {
  storms: StormCell[]
  locations: LocationItem[]
  satelliteWatches?: ConvectiveWatch[]
  satelliteImage?: SatelliteImageMeta | null
  lightning?: LightningStrike[]
  /** Talhão outlines (FASE 27, ADR-0024) — visual only, colored by crop. */
  plotBoundaries?: PlotBoundary[]
  /** Real satellite imagery basemap (Esri World Imagery) instead of the
   * OSM vector-style streets basemap. */
  satelliteBasemap?: boolean
}

export interface StormMapHandle {
  /** Centers and zooms the map on a point — e.g. clicking a satellite watch row. */
  flyTo(latitude: number, longitude: number): void
  /** Enters click-to-add-vertex polygon drawing mode. */
  startDrawing(): void
  /** Ends drawing and returns the closed ring's coordinates ([lng,lat][]),
   * or `null` if fewer than 3 points were placed. Always clears the sketch,
   * successful or not. */
  finishDrawing(): [number, number][] | null
  /** Aborts drawing without returning anything, clearing the sketch. */
  cancelDrawing(): void
  /** Enters click-to-place-a-point mode — the very next map click calls
   * `onPick(latitude, longitude)` once and exits the mode automatically. */
  startPointPick(onPick: (latitude: number, longitude: number) => void): void
  /** Aborts point-picking without calling back. */
  cancelPointPick(): void
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
    // Free, no API key (same usage pattern as this project's other no-key
    // sources — Open-Meteo, Nominatim): real satellite imagery basemap for
    // drawing talhão outlines against, toggled via `satelliteBasemap`.
    esri: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution: 'Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [
    { id: 'osm', type: 'raster', source: 'osm' },
    { id: 'esri', type: 'raster', source: 'esri', layout: { visibility: 'none' } },
  ],
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

function plotBoundariesGeoJSON(plots: PlotBoundary[]) {
  return {
    type: 'FeatureCollection' as const,
    features: plots.map((p) => ({
      type: 'Feature' as const,
      geometry: { type: 'Polygon' as const, coordinates: p.coordinates },
      properties: { name: p.name, color: p.color },
    })),
  }
}

function sketchLineGeoJSON(points: [number, number][]) {
  return {
    type: 'FeatureCollection' as const,
    features:
      points.length < 2
        ? []
        : [
            {
              type: 'Feature' as const,
              geometry: { type: 'LineString' as const, coordinates: [...points, points[0]] },
              properties: {},
            },
          ],
  }
}

function sketchPointsGeoJSON(points: [number, number][]) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map((p) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: p },
      properties: {},
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
  {
    storms,
    locations,
    satelliteWatches = [],
    satelliteImage = null,
    lightning = [],
    plotBoundaries = [],
    satelliteBasemap = false,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const readyRef = useRef(false)
  const hasFitBoundsRef = useRef(false)
  const drawingActiveRef = useRef(false)
  const drawingPointsRef = useRef<[number, number][]>([])
  const pointPickCallbackRef = useRef<((latitude: number, longitude: number) => void) | null>(null)

  function updateSketchSources() {
    const map = mapRef.current
    if (!map) return
    const line = map.getSource('draw-sketch-line') as GeoJSONSource | undefined
    const points = map.getSource('draw-sketch-points') as GeoJSONSource | undefined
    line?.setData(sketchLineGeoJSON(drawingPointsRef.current))
    points?.setData(sketchPointsGeoJSON(drawingPointsRef.current))
  }

  useImperativeHandle(ref, () => ({
    flyTo(latitude: number, longitude: number) {
      mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 9, duration: 600 })
    },
    startDrawing() {
      drawingPointsRef.current = []
      drawingActiveRef.current = true
      if (mapRef.current) mapRef.current.getCanvas().style.cursor = 'crosshair'
      updateSketchSources()
    },
    finishDrawing() {
      drawingActiveRef.current = false
      if (mapRef.current) mapRef.current.getCanvas().style.cursor = ''
      const pts = drawingPointsRef.current
      drawingPointsRef.current = []
      updateSketchSources()
      if (pts.length < 3) return null
      return [...pts, pts[0]]
    },
    cancelDrawing() {
      drawingActiveRef.current = false
      if (mapRef.current) mapRef.current.getCanvas().style.cursor = ''
      drawingPointsRef.current = []
      updateSketchSources()
    },
    startPointPick(onPick) {
      pointPickCallbackRef.current = onPick
      if (mapRef.current) mapRef.current.getCanvas().style.cursor = 'crosshair'
    },
    cancelPointPick() {
      pointPickCallbackRef.current = null
      if (mapRef.current) mapRef.current.getCanvas().style.cursor = ''
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

    map.on('click', (e) => {
      if (pointPickCallbackRef.current) {
        const callback = pointPickCallbackRef.current
        pointPickCallbackRef.current = null
        map.getCanvas().style.cursor = ''
        callback(e.lngLat.lat, e.lngLat.lng)
        return
      }
      if (!drawingActiveRef.current) return
      drawingPointsRef.current = [...drawingPointsRef.current, [e.lngLat.lng, e.lngLat.lat]]
      updateSketchSources()
    })

    map.on('load', () => {
      map.addSource('plot-boundaries', { type: 'geojson', data: plotBoundariesGeoJSON([]) })
      // Under everything else — an area outline, never competing with
      // point markers or the drawing-in-progress sketch on top of it.
      map.addLayer({
        id: 'plot-boundaries-fill',
        type: 'fill',
        source: 'plot-boundaries',
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.2 },
      })
      map.addLayer({
        id: 'plot-boundaries-line',
        type: 'line',
        source: 'plot-boundaries',
        paint: { 'line-color': ['get', 'color'], 'line-width': 2 },
      })

      map.addSource('draw-sketch-line', { type: 'geojson', data: sketchLineGeoJSON([]) })
      map.addLayer({
        id: 'draw-sketch-line',
        type: 'line',
        source: 'draw-sketch-line',
        paint: { 'line-color': '#4cc2e6', 'line-width': 2, 'line-dasharray': [2, 1] },
      })
      map.addSource('draw-sketch-points', { type: 'geojson', data: sketchPointsGeoJSON([]) })
      map.addLayer({
        id: 'draw-sketch-points',
        type: 'circle',
        source: 'draw-sketch-points',
        paint: {
          'circle-radius': 5,
          'circle-color': '#4cc2e6',
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#0b1120',
        },
      })

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
      const plots = map.getSource('plot-boundaries') as GeoJSONSource | undefined
      if (!cells || !locs || !watches || !strikes || !plots) return
      cells.setData(cellsGeoJSON(storms))
      locs.setData(locationsGeoJSON(locations))
      watches.setData(satelliteWatchesGeoJSON(satelliteWatches))
      strikes.setData(lightningGeoJSON(lightning))
      plots.setData(plotBoundariesGeoJSON(plotBoundaries))

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

      // Only ever auto-fit once, the first time there's something to show —
      // re-fitting on every poll (storms/locations refresh every 30s) was
      // fighting the user's own zoom/pan on each cycle. Flying to a specific
      // point (selecting a location, clicking a watch/strike) still works
      // via `flyTo`, independent of this.
      if (!hasFitBoundsRef.current) {
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
          hasFitBoundsRef.current = true
        }
      }
    }

    if (readyRef.current) apply()
    else map.once('load', apply)
  }, [storms, locations, satelliteWatches, satelliteImage, lightning, plotBoundaries])

  // Toggle basemap: real satellite imagery vs. the OSM streets style.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (!map.getLayer('osm') || !map.getLayer('esri')) return
      map.setLayoutProperty('osm', 'visibility', satelliteBasemap ? 'none' : 'visible')
      map.setLayoutProperty('esri', 'visibility', satelliteBasemap ? 'visible' : 'none')
    }
    if (readyRef.current) apply()
    else map.once('load', apply)
  }, [satelliteBasemap])

  return <div className="map" ref={containerRef} />
})
