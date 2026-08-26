import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { ApiError, api, logout } from '../api'
import { StormMapView } from '../components/StormMapView'
import type {
  AlertItem,
  ConvectiveWatch,
  LightningStrike,
  LocationItem,
  Me,
  RiskLevel,
  StormCell,
  StormRisk,
} from '../types'
import { LEVEL_COLOR, LEVEL_LABEL, colors } from '../theme'

interface Props {
  onLogout: () => void
}

interface LocationWithRisk {
  location: LocationItem
  risk: StormRisk | null
}

function timeAgo(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (minutes < 1) return 'agora'
  if (minutes < 60) return `há ${minutes} min`
  return `há ${Math.round(minutes / 60)}h`
}

export function HomeScreen({ onLogout }: Props) {
  const [me, setMe] = useState<Me | null>(null)
  const [verificationSent, setVerificationSent] = useState<
    'sent' | 'already-verified' | 'error' | null
  >(null)
  const [deletingAccount, setDeletingAccount] = useState(false)
  const [items, setItems] = useState<LocationWithRisk[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [storms, setStorms] = useState<StormCell[]>([])
  const [lightning, setLightning] = useState<LightningStrike[]>([])
  const [satelliteWatches, setSatelliteWatches] = useState<ConvectiveWatch[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const [locations, alertList, meResult, stormList, lightningList, watchList] =
        await Promise.all([
          api.locations(),
          api.alerts(),
          api.me(),
          api.storms(),
          api.lightning(),
          api.satelliteWatches(),
        ])
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
      setMe(meResult)
      setStorms(stormList)
      setLightning(lightningList)
      setSatelliteWatches(watchList)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await logout()
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
    await logout()
    onLogout()
  }

  async function handleResendVerification() {
    setVerificationSent(null)
    try {
      const { sent } = await api.resendVerification()
      setVerificationSent(sent ? 'sent' : 'already-verified')
    } catch {
      setVerificationSent('error')
    }
  }

  function handleDeleteAccount() {
    Alert.alert(
      'Excluir conta',
      'Excluir sua conta é permanente e apaga todos os seus locais, alertas e histórico. Tem certeza?',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Excluir',
          style: 'destructive',
          onPress: async () => {
            setDeletingAccount(true)
            try {
              await api.deleteAccount()
            } catch {
              // Mesmo se a chamada falhar após a conta já ter sumido
              // (token já inválido), sair localmente ainda é o certo.
            }
            await logout()
            onLogout()
          },
        },
      ],
    )
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
        <View style={styles.headerActions}>
          <TouchableOpacity onPress={handleDeleteAccount} disabled={deletingAccount}>
            <Text style={styles.deleteAccount}>
              {deletingAccount ? 'Excluindo…' : 'Excluir conta'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={handleLogout}>
            <Text style={styles.logout}>Sair</Text>
          </TouchableOpacity>
        </View>
      </View>

      {me && !me.email_verified && (
        <View style={styles.verifyBanner}>
          <Text style={styles.verifyText}>✉️ Confirme seu e-mail para garantir acesso total.</Text>
          {verificationSent === 'sent' ? (
            <Text style={styles.verifySub}>Link reenviado — confira sua caixa de entrada.</Text>
          ) : verificationSent === 'already-verified' ? (
            <Text style={styles.verifySub}>Seu e-mail já foi confirmado.</Text>
          ) : verificationSent === 'error' ? (
            <Text style={styles.error}>Falha ao reenviar. Tente de novo em instantes.</Text>
          ) : (
            <TouchableOpacity onPress={handleResendVerification}>
              <Text style={styles.link}>Reenviar e-mail de confirmação</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {error && <Text style={styles.error}>⚠️ {error}</Text>}

      {items.length > 0 && (
        <StormMapView
          locations={items.map((i) => i.location)}
          storms={storms}
          lightning={lightning}
          satelliteWatches={satelliteWatches}
        />
      )}

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

      <Text style={styles.section}>⚡ Raios</Text>
      {lightning.length === 0 && (
        <Text style={styles.empty}>Nenhum raio detectado no momento.</Text>
      )}
      {lightning.slice(0, 10).map((strike) => (
        <View key={strike.id} style={styles.card}>
          <View style={[styles.dot, { backgroundColor: colors.yellow }]} />
          <View style={styles.grow}>
            <Text style={styles.sub}>
              {strike.latitude.toFixed(2)}, {strike.longitude.toFixed(2)}
              {strike.is_mock ? ' · MOCK' : ''}
            </Text>
          </View>
          <Text style={styles.radius}>{timeAgo(strike.detected_at)}</Text>
        </View>
      ))}

      <Text style={styles.section}>Observações via satélite</Text>
      {satelliteWatches.filter((w) => w.is_active).length === 0 && (
        <Text style={styles.empty}>Nenhuma observação ativa.</Text>
      )}
      {satelliteWatches
        .filter((w) => w.is_active)
        .map((watch) => (
          <View key={watch.id} style={styles.card}>
            <View style={[styles.dot, { backgroundColor: colors.inkMute }]} />
            <View style={styles.grow}>
              <Text style={styles.sub}>
                {watch.min_brightness_temp_k.toFixed(0)}K
                {watch.area_km2 != null ? ` · ${watch.area_km2.toFixed(0)} km²` : ''}
                {watch.is_mock ? ' · MOCK' : ''}
              </Text>
            </View>
            <Text style={styles.radius}>{timeAgo(watch.detected_at)}</Text>
          </View>
        ))}

      {/* Hardening ADR-0036 — shown on the home screen, not just documented
          in the README. Never let StormPulse be mistaken for a substitute
          for official alerts. */}
      <Text style={styles.disclaimer}>
        ⚠️ StormPulse não substitui alertas oficiais (INMET, Defesa Civil,
        CEMADEN). Em qualquer situação de risco real, siga os canais oficiais.
      </Text>
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
        {risk?.ai_summary && <Text style={styles.aiSummary}>{risk.ai_summary}</Text>}
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
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  logout: { color: colors.inkDim, fontSize: 14 },
  deleteAccount: { color: colors.inkMute, fontSize: 13 },
  error: { color: colors.red, marginTop: 12 },
  verifyBanner: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginTop: 14,
  },
  verifyText: { color: colors.ink, fontSize: 13 },
  verifySub: { color: colors.inkMute, fontSize: 12, marginTop: 4 },
  link: { color: colors.accent, fontSize: 13, marginTop: 4 },
  aiSummary: { color: colors.inkDim, fontSize: 12, marginTop: 6, fontStyle: 'italic' },
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
  disclaimer: {
    color: colors.inkMute,
    fontSize: 11,
    marginTop: 24,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  badge: { borderRadius: 999, paddingHorizontal: 9, paddingVertical: 3 },
  badgeText: { color: '#04121f', fontSize: 11, fontWeight: '700' },
})
