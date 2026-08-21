import { useState } from 'react'
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'
import MapView, { Polygon, type LatLng, type MapPressEvent } from 'react-native-maps'
import { cropColor } from '../cropColors'
import type { LocationItem } from '../types'
import { colors } from '../theme'

interface Props {
  farm: LocationItem
  /** Other plots under the same farm, drawn for context while sketching a
   * new/updated boundary — never selectable, just a visual reference. */
  existingPlots: LocationItem[]
  onComplete: (boundaryGeojson: string) => void
  onCancel: () => void
}

function toGeoJson(points: LatLng[]): string {
  const ring = [...points, points[0]].map((p) => [p.longitude, p.latitude])
  return JSON.stringify({ type: 'Polygon', coordinates: [ring] })
}

function parseBoundary(boundaryGeojson: string | null): LatLng[] | null {
  if (!boundaryGeojson) return null
  try {
    const parsed = JSON.parse(boundaryGeojson) as { coordinates: [number, number][][] }
    return parsed.coordinates[0].map(([longitude, latitude]) => ({ latitude, longitude }))
  } catch {
    return null
  }
}

export function PlotBoundaryMapScreen({ farm, existingPlots, onComplete, onCancel }: Props) {
  const [points, setPoints] = useState<LatLng[]>([])
  const [satellite, setSatellite] = useState(true)

  function handleMapPress(e: MapPressEvent) {
    setPoints((prev) => [...prev, e.nativeEvent.coordinate])
  }

  function handleUndo() {
    setPoints((prev) => prev.slice(0, -1))
  }

  function handleFinish() {
    if (points.length < 3) return
    onComplete(toGeoJson(points))
  }

  return (
    <View style={styles.screen}>
      <MapView
        style={StyleSheet.absoluteFill}
        mapType={satellite ? 'satellite' : 'standard'}
        initialRegion={{
          latitude: farm.latitude,
          longitude: farm.longitude,
          latitudeDelta: 0.05,
          longitudeDelta: 0.05,
        }}
        onPress={handleMapPress}
      >
        {existingPlots.map((plot) => {
          const ring = parseBoundary(plot.boundary_geojson)
          if (!ring) return null
          return (
            <Polygon
              key={plot.id}
              coordinates={ring}
              fillColor={(plot.color ?? cropColor(plot.crop)) + '33'}
              strokeColor={plot.color ?? cropColor(plot.crop)}
              strokeWidth={2}
            />
          )
        })}
        {points.length >= 2 && (
          <Polygon
            coordinates={points}
            fillColor="rgba(76, 194, 230, 0.2)"
            strokeColor={colors.accent}
            strokeWidth={2}
          />
        )}
      </MapView>

      <View style={styles.topBar}>
        <Text style={styles.hint}>Toque no mapa pra marcar os cantos do talhão</Text>
        <TouchableOpacity onPress={() => setSatellite((v) => !v)}>
          <Text style={styles.satelliteToggle}>
            {satellite ? '🗺️ mapa normal' : '🛰️ satélite'}
          </Text>
        </TouchableOpacity>
      </View>

      <View style={styles.bottomBar}>
        <Text style={styles.pointCount}>{points.length} ponto(s)</Text>
        <TouchableOpacity
          style={styles.btnGhost}
          onPress={handleUndo}
          disabled={points.length === 0}
        >
          <Text style={styles.btnGhostText}>Desfazer</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.btnGhost} onPress={onCancel}>
          <Text style={styles.btnGhostText}>Cancelar</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.btn, points.length < 3 && styles.btnDisabled]}
          onPress={handleFinish}
          disabled={points.length < 3}
        >
          <Text style={styles.btnText}>Concluir</Text>
        </TouchableOpacity>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  topBar: {
    position: 'absolute',
    top: 48,
    left: 12,
    right: 12,
    backgroundColor: 'rgba(11, 17, 32, 0.9)',
    borderRadius: 10,
    padding: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  hint: { color: colors.ink, fontSize: 13, flex: 1 },
  satelliteToggle: { color: colors.accent, fontSize: 13, marginLeft: 10 },
  bottomBar: {
    position: 'absolute',
    bottom: 24,
    left: 12,
    right: 12,
    backgroundColor: 'rgba(11, 17, 32, 0.9)',
    borderRadius: 10,
    padding: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  pointCount: { color: colors.inkMute, fontSize: 12, flex: 1 },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 14,
  },
  btnDisabled: { opacity: 0.4 },
  btnText: { color: '#04121f', fontWeight: '700' },
  btnGhost: {
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  btnGhostText: { color: colors.inkDim, fontSize: 13 },
})
