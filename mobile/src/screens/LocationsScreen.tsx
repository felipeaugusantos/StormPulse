import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import * as Location from 'expo-location'
import { ApiError, api, clearToken } from '../api'
import { isPushSupported, subscribeToExpoPush } from '../push'
import { reverseGeocodeCity, searchCity } from '../geocode'
import type { CitySearchResult, LocationItem } from '../types'
import { colors } from '../theme'

interface Props {
  onLogout: () => void
}

const SEARCH_DEBOUNCE_MS = 400

export function LocationsScreen({ onLogout }: Props) {
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pushStatus, setPushStatus] = useState<'idle' | 'subscribing' | 'on' | 'error'>('idle')

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CitySearchResult[]>([])
  const [picked, setPicked] = useState<CitySearchResult | null>(null)
  const [name, setName] = useState('')
  const [radiusKm, setRadiusKm] = useState('50')
  const [creating, setCreating] = useState(false)
  const [locating, setLocating] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [addingPlotFor, setAddingPlotFor] = useState<string | null>(null)
  const [plotName, setPlotName] = useState('')
  const [plotCrop, setPlotCrop] = useState('')
  const [creatingPlot, setCreatingPlot] = useState(false)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      setLocations(await api.locations())
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

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      setResults(await searchCity(query))
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  async function useMyLocation() {
    setLocating(true)
    setError(null)
    try {
      const { status } = await Location.requestForegroundPermissionsAsync()
      if (status !== 'granted') {
        setError('Permissão de localização negada')
        return
      }
      const position = await Location.getCurrentPositionAsync({})
      const { latitude, longitude } = position.coords
      reverseGeocodeCity(latitude, longitude, (place) => {
        pick({ label: place ?? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`, latitude, longitude })
      })
    } catch {
      setError('Não foi possível obter sua localização')
    } finally {
      setLocating(false)
    }
  }

  function pick(result: CitySearchResult) {
    setPicked(result)
    setResults([])
    setQuery('')
    setName(result.label.split(',')[0] ?? result.label)
    setRadiusKm('50')
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
        radius_km: Number(radiusKm) || 50,
      })
      setLocations((prev) => [...prev, created])
      setPicked(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar o local')
    } finally {
      setCreating(false)
    }
  }

  function startAddingPlot(farm: LocationItem) {
    setAddingPlotFor(farm.id)
    setPlotName('')
    setPlotCrop('')
  }

  async function createPlot(farm: LocationItem) {
    setCreatingPlot(true)
    setError(null)
    try {
      const created = await api.createLocation({
        name: plotName.trim() || 'Talhão',
        latitude: farm.latitude,
        longitude: farm.longitude,
        parent_location_id: farm.id,
        crop: plotCrop.trim() || undefined,
      })
      setLocations((prev) => [...prev, created])
      setAddingPlotFor(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar o talhão')
    } finally {
      setCreatingPlot(false)
    }
  }

  function removeLocation(location: LocationItem) {
    Alert.alert(
      'Remover local',
      `Remover "${location.name}"${location.parent_location_id == null ? ' e todos os seus talhões' : ''}?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Remover',
          style: 'destructive',
          onPress: async () => {
            try {
              await api.deleteLocation(location.id)
              setLocations((prev) =>
                prev.filter((l) => l.id !== location.id && l.parent_location_id !== location.id),
              )
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Não foi possível remover')
            }
          },
        },
      ],
    )
  }

  async function handleEnablePush() {
    setPushStatus('subscribing')
    try {
      await subscribeToExpoPush()
      setPushStatus('on')
    } catch (err) {
      setPushStatus('error')
      setError(err instanceof Error ? err.message : 'Não foi possível ativar notificações')
    }
  }

  const farms = locations.filter((l) => l.parent_location_id == null)

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.accent} />
      }
    >
      <View style={styles.header}>
        <Text style={styles.title}>📍 Locais</Text>
        {isPushSupported() && pushStatus !== 'on' && (
          <TouchableOpacity onPress={handleEnablePush} disabled={pushStatus === 'subscribing'}>
            <Text style={styles.pushButton}>
              {pushStatus === 'subscribing' ? 'Ativando…' : '🔔 Ativar notificações'}
            </Text>
          </TouchableOpacity>
        )}
        {pushStatus === 'on' && <Text style={styles.pushOn}>🔔 Ativo</Text>}
      </View>

      {error && <Text style={styles.error}>⚠️ {error}</Text>}

      {picked ? (
        <View style={styles.form}>
          <Text style={styles.label}>Nome</Text>
          <TextInput style={styles.input} value={name} onChangeText={setName} />
          <Text style={styles.label}>Raio (km)</Text>
          <TextInput
            style={styles.input}
            value={radiusKm}
            onChangeText={setRadiusKm}
            keyboardType="numeric"
          />
          <View style={styles.formActions}>
            <TouchableOpacity
              style={styles.btn}
              onPress={createLocation}
              disabled={creating}
            >
              <Text style={styles.btnText}>{creating ? 'Adicionando…' : 'Adicionar'}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.btnGhost}
              onPress={() => setPicked(null)}
              disabled={creating}
            >
              <Text style={styles.btnGhostText}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : (
        <>
          <TextInput
            style={styles.input}
            placeholder="Buscar cidade (ex: Ribeirão Preto)"
            placeholderTextColor={colors.inkMute}
            value={query}
            onChangeText={setQuery}
          />
          <TouchableOpacity onPress={useMyLocation} disabled={locating} style={styles.myLocation}>
            <Text style={styles.myLocationText}>
              {locating ? <ActivityIndicator color={colors.accent} /> : '📍 usar minha localização'}
            </Text>
          </TouchableOpacity>
          {results.map((r) => (
            <TouchableOpacity
              key={`${r.latitude},${r.longitude}`}
              style={styles.searchResult}
              onPress={() => pick(r)}
            >
              <Text style={styles.searchResultText}>{r.label}</Text>
            </TouchableOpacity>
          ))}
        </>
      )}

      {farms.length === 0 && !refreshing && (
        <Text style={styles.empty}>Nenhum local cadastrado ainda.</Text>
      )}

      {farms.map((farm) => {
        const plots = locations.filter((l) => l.parent_location_id === farm.id)
        return (
          <View key={farm.id} style={styles.farmCard}>
            <View style={styles.farmHeader}>
              <View style={styles.grow}>
                <Text style={styles.farmName}>{farm.name}</Text>
                <Text style={styles.sub}>
                  {farm.kind} · raio {farm.radius_km} km
                </Text>
              </View>
              <TouchableOpacity onPress={() => startAddingPlot(farm)}>
                <Text style={styles.smallBtn}>+ talhão</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => removeLocation(farm)}>
                <Text style={styles.smallBtnDanger}>remover</Text>
              </TouchableOpacity>
            </View>

            {plots.map((plot) => (
              <View key={plot.id} style={styles.plotRow}>
                <View style={styles.grow}>
                  <Text style={styles.plotName}>🌱 {plot.name}</Text>
                  <Text style={styles.sub}>{plot.crop ?? 'cultura não informada'}</Text>
                </View>
                <TouchableOpacity onPress={() => removeLocation(plot)}>
                  <Text style={styles.smallBtnDanger}>remover</Text>
                </TouchableOpacity>
              </View>
            ))}

            {addingPlotFor === farm.id && (
              <View style={styles.plotForm}>
                <Text style={styles.label}>Nome do talhão</Text>
                <TextInput style={styles.input} value={plotName} onChangeText={setPlotName} />
                <Text style={styles.label}>Cultura (opcional)</Text>
                <TextInput
                  style={styles.input}
                  value={plotCrop}
                  onChangeText={setPlotCrop}
                  placeholder="soja, milho, café…"
                  placeholderTextColor={colors.inkMute}
                />
                <View style={styles.formActions}>
                  <TouchableOpacity
                    style={styles.btn}
                    onPress={() => createPlot(farm)}
                    disabled={creatingPlot}
                  >
                    <Text style={styles.btnText}>
                      {creatingPlot ? 'Adicionando…' : 'Adicionar talhão'}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.btnGhost}
                    onPress={() => setAddingPlotFor(null)}
                    disabled={creatingPlot}
                  >
                    <Text style={styles.btnGhostText}>Cancelar</Text>
                  </TouchableOpacity>
                </View>
              </View>
            )}
          </View>
        )
      })}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { padding: 16, paddingTop: 56, paddingBottom: 32 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 16, gap: 10 },
  title: { color: colors.ink, fontSize: 22, fontWeight: '700', flex: 1 },
  pushButton: { color: colors.accent, fontSize: 13 },
  pushOn: { color: colors.green, fontSize: 13 },
  error: { color: colors.red, marginBottom: 12 },
  empty: { color: colors.inkMute, fontSize: 14, marginTop: 8 },
  input: {
    backgroundColor: colors.panel2,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    color: colors.ink,
    marginBottom: 8,
  },
  label: { color: colors.inkMute, fontSize: 12, marginBottom: 2 },
  myLocation: { paddingVertical: 8 },
  myLocationText: { color: colors.accent, fontSize: 13 },
  searchResult: {
    paddingVertical: 10,
    borderBottomColor: colors.line,
    borderBottomWidth: 1,
  },
  searchResultText: { color: colors.ink, fontSize: 14 },
  form: {
    backgroundColor: colors.panel2,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
  },
  formActions: { flexDirection: 'row', gap: 10, marginTop: 6 },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
    flex: 1,
    alignItems: 'center',
  },
  btnText: { color: '#04121f', fontWeight: '700' },
  btnGhost: {
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
    flex: 1,
    alignItems: 'center',
  },
  btnGhostText: { color: colors.inkDim },
  farmCard: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  farmHeader: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1 },
  farmName: { color: colors.ink, fontSize: 16, fontWeight: '600' },
  sub: { color: colors.inkMute, fontSize: 12, marginTop: 2 },
  smallBtn: { color: colors.accent, fontSize: 12 },
  smallBtnDanger: { color: colors.red, fontSize: 12 },
  plotRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginTop: 10,
    marginLeft: 16,
    paddingLeft: 10,
    borderLeftColor: colors.line,
    borderLeftWidth: 2,
  },
  plotName: { color: colors.ink, fontSize: 14, fontWeight: '600' },
  plotForm: { marginTop: 10, marginLeft: 16 },
})
