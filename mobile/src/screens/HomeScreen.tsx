import { useCallback, useEffect, useState } from 'react'
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { ApiError, api, clearToken } from '../api'
import type { AlertItem, LocationItem, RiskLevel, StormRisk } from '../types'
import { LEVEL_COLOR, LEVEL_LABEL, colors } from '../theme'

interface Props {
  onLogout: () => void
}

interface LocationWithRisk {
  location: LocationItem
  risk: StormRisk | null
}

export function HomeScreen({ onLogout }: Props) {
  const [items, setItems] = useState<LocationWithRisk[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const [locations, alertList] = await Promise.all([api.locations(), api.alerts()])
      const withRisk = await Promise.all(
        locations.map(async (location) => {
          try {
            return { location, risk: await api.risk(location.id) }
          } catch {
            return { location, risk: null }
          }
        }),
      )
      setItems(withRisk)
      setAlerts(alertList)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await clearToken()
        onLogout()
        return
      }
      setError(err instanceof Error ? err.message : 'Erro ao carregar')
    } finally {
      setRefreshing(false)
    }
  }, [onLogout])

  useEffect(() => {
    load()
  }, [load])

  async function handleLogout() {
    await clearToken()
    onLogout()
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.accent} />
      }
    >
      <View style={styles.header}>
        <Text style={styles.brand}>
          ⚡ Storm<Text style={{ color: colors.accent }}>Pulse</Text>
        </Text>
        <TouchableOpacity onPress={handleLogout}>
          <Text style={styles.logout}>Sair</Text>
        </TouchableOpacity>
      </View>

      {error && <Text style={styles.error}>⚠️ {error}</Text>}

      <Text style={styles.section}>Alertas</Text>
      {alerts.length === 0 && <Text style={styles.empty}>Nenhum alerta ativo.</Text>}
      {alerts.map((a) => (
        <View key={a.id} style={styles.card}>
          <View style={[styles.badge, { backgroundColor: LEVEL_COLOR[a.level] }]}>
            <Text style={styles.badgeText}>{a.level.toUpperCase()}</Text>
          </View>
          <View style={styles.grow}>
            <Text style={styles.title}>{a.title}</Text>
            <Text style={styles.sub}>{a.message}</Text>
          </View>
        </View>
      ))}

      <Text style={styles.section}>Locais monitorados</Text>
      {items.length === 0 && <Text style={styles.empty}>Nenhum local cadastrado.</Text>}
      {items.map(({ location, risk }) => (
        <LocationCard key={location.id} location={location} risk={risk} />
      ))}
    </ScrollView>
  )
}

function LocationCard({ location, risk }: LocationWithRisk) {
  const level: RiskLevel = risk?.severity ?? 'green'
  return (
    <View style={styles.card}>
      <View style={[styles.dot, { backgroundColor: LEVEL_COLOR[level] }]} />
      <View style={styles.grow}>
        <Text style={styles.title}>{location.name}</Text>
        {risk ? (
          <Text style={styles.sub}>
            {LEVEL_LABEL[level]}
            {risk.eta_minutes != null ? ` · ETA ~${risk.eta_minutes} min` : ''}
            {risk.storm_distance_km != null ? ` · ${risk.storm_distance_km.toFixed(0)} km` : ''}
            {risk.is_mock ? ' · MOCK' : ''}
          </Text>
        ) : (
          <Text style={styles.sub}>Sem avaliação de risco no momento</Text>
        )}
      </View>
      <Text style={styles.radius}>{location.radius_km} km</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { padding: 16, paddingTop: 56 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  brand: { color: colors.ink, fontSize: 22, fontWeight: '700' },
  logout: { color: colors.inkDim, fontSize: 14 },
  error: { color: colors.red, marginTop: 12 },
  section: {
    color: colors.inkMute,
    fontSize: 12,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginTop: 22,
    marginBottom: 8,
  },
  empty: { color: colors.inkMute, fontSize: 14 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  grow: { flex: 1 },
  title: { color: colors.ink, fontSize: 15, fontWeight: '600' },
  sub: { color: colors.inkMute, fontSize: 12, marginTop: 2 },
  dot: { width: 12, height: 12, borderRadius: 6 },
  radius: { color: colors.inkDim, fontFamily: 'monospace', fontSize: 12 },
  badge: { borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3 },
  badgeText: { color: '#04121f', fontSize: 11, fontWeight: '700' },
})
