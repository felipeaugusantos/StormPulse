import { StyleSheet, Text, View } from 'react-native'
import MapView, { Callout, Circle, Marker } from 'react-native-maps'
import type { ConvectiveWatch, LightningStrike, LocationItem, StormCell } from '../types'
import { colors } from '../theme'

// Same palette as web/src/components/StormMap.tsx's SEVERITY_COLOR — kept
// in sync so a cell reads the same severity color on both platforms.
const SEVERITY_COLOR: Record<StormCell['severity'], string> = {
  weak: colors.green,
  moderate: colors.yellow,
  strong: colors.orange,
  severe: colors.red,
}

interface Props {
  locations: LocationItem[]
  storms: StormCell[]
  lightning: LightningStrike[]
  satelliteWatches: ConvectiveWatch[]
  height?: number
}

/** Visual storm map (item 5, paridade mobile) — locations + monitored
 * radius, storm cells, lightning strikes and satellite convective watches
 * plotted on the map that already existed for talhão boundary drawing
 * (`PlotBoundaryMapScreen.tsx`), just with a different marker set. Purely
 * a live snapshot — no interaction beyond the map's own pan/zoom/callouts. */
export function StormMapView({
  locations,
  storms,
  lightning,
  satelliteWatches,
  height = 260,
}: Props) {
  const center = locations[0] ?? { latitude: -23.5, longitude: -46.6 }

  return (
    <View style={[styles.wrap, { height }]}>
      <MapView
        style={StyleSheet.absoluteFill}
        initialRegion={{
          latitude: center.latitude,
          longitude: center.longitude,
          latitudeDelta: 4,
          longitudeDelta: 4,
        }}
      >
        {locations.map((location) => (
          <View key={location.id}>
            <Marker
              coordinate={location}
              pinColor={colors.accent}
              title={location.name}
              description={`raio monitorado: ${location.radius_km} km`}
            />
            <Circle
              center={location}
              radius={location.radius_km * 1000}
              strokeColor={colors.accent}
              fillColor="rgba(76, 194, 230, 0.08)"
              strokeWidth={1}
            />
          </View>
        ))}

        {storms.map((cell) => (
          <Circle
            key={cell.id}
            center={cell}
            radius={Math.max(3000, Math.sqrt((cell.area_km2 ?? 20) / Math.PI) * 1000)}
            strokeColor={SEVERITY_COLOR[cell.severity]}
            fillColor={SEVERITY_COLOR[cell.severity] + '55'}
            strokeWidth={2}
          />
        ))}
        {storms.map((cell) => (
          <Marker key={`${cell.id}-marker`} coordinate={cell} anchor={{ x: 0.5, y: 0.5 }}>
            <View style={styles.tapTarget} />
            <Callout>
              <View style={{ maxWidth: 200 }}>
                <Text style={{ fontWeight: '700' }}>{cell.severity.toUpperCase()}</Text>
                <Text>
                  {cell.max_reflectivity != null ? `${cell.max_reflectivity.toFixed(0)} dBZ` : ''}
                  {cell.is_mock ? ' · MOCK' : ''}
                </Text>
              </View>
            </Callout>
          </Marker>
        ))}

        {lightning.map((strike) => (
          <Circle
            key={strike.id}
            center={strike}
            radius={800}
            strokeColor={colors.yellow}
            fillColor={colors.yellow + '88'}
            strokeWidth={1}
          />
        ))}

        {satelliteWatches
          .filter((w) => w.is_active)
          .map((watch) => (
            <Circle
              key={watch.id}
              center={watch}
              radius={Math.max(5000, Math.sqrt((watch.area_km2 ?? 3000) / Math.PI) * 1000)}
              strokeColor={colors.inkMute}
              fillColor="rgba(111, 127, 158, 0.15)"
              strokeWidth={1}
              lineDashPattern={[6, 4]}
            />
          ))}
      </MapView>
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: 12,
    overflow: 'hidden',
    borderColor: colors.line,
    borderWidth: 1,
    marginBottom: 10,
  },
  tapTarget: { width: 28, height: 28 },
})
