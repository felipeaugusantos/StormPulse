import { useCallback, useEffect, useState } from 'react'
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { ApiError, api, logout } from '../api'
import {
  classifyDiseaseRisk,
  classifyFrostDays,
  classifyVpd,
  evaluateTrafficability,
  formatFrostDays,
  growingDegreeDays,
  vaporPressureDeficitKpa,
  waterBalanceMm,
  type DiseaseRisk,
  type Trafficability,
  type VpdLevel,
} from '../agro'
import { classifyCape, type CapeLevel } from '../storm'
import type {
  ForecastComparison,
  ForecastPoint,
  LocationItem,
  SprayWindow,
  VegetationIndex,
  VegetationSeries,
} from '../types'
import { colors } from '../theme'

interface Props {
  onLogout: () => void
}

// Mirrors the backend/web defaults — see ADR-0014/ADR-0018/ADR-0021.
const FROST_THRESHOLD_C = 3
const FROST_LIGHT_THRESHOLD_C = 6
const TRAFFICABILITY_DRY_DAYS = 2
const TRAFFICABILITY_RAIN_THRESHOLD_MM = 1
const TRAFFICABILITY_LOOKAHEAD_DAYS = 2
const GDD_BASE_TEMP_C = 10
const DISEASE_RISK_THRESHOLDS = { humidityThresholdPercent: 80, minTempC: 15, maxTempC: 30 }
const VEGETATION_INDICES: VegetationIndex[] = ['ndvi', 'ndre', 'evi', 'ndmi', 'ndwi']

interface AgroEntry {
  location: LocationItem
  severeFrostDays: ForecastPoint[]
  lightFrostDays: ForecastPoint[]
  sprayWindow: SprayWindow | null
  rainfallTotalMm: number | null
  rainfallDays: number
  trafficability: Trafficability | null
  capeJkg: number | null
  capeLevel: CapeLevel | null
  windGustMaxKmh: number | null
  waterBalanceMm: number | null
  gddC: number | null
  diseaseRisk: DiseaseRisk
  vpdKpa: number | null
  vpdLevel: VpdLevel
  forecastComparison: ForecastComparison | null
  vegetation: VegetationSeries[]
  error: string | null
}

const CAPE_LABEL: Record<CapeLevel, string> = {
  weak: 'fraca',
  moderate: 'moderada',
  strong: 'forte',
  extreme: 'extrema',
}

const VPD_LABEL: Record<VpdLevel, string> = {
  low: 'baixo (transpiração reduzida)',
  ideal: 'ideal',
  high: 'alto (estresse hídrico)',
  unknown: 'indisponível',
}

export function AgroScreen({ onLogout }: Props) {
  const [entries, setEntries] = useState<AgroEntry[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const locations = (await api.locations()).filter((l) => l.is_active)
      const results = await Promise.all(locations.map(loadEntry))
      setEntries(results)
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

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.accent} />
      }
    >
      <Text style={styles.title}>🌾 Agro</Text>
      {error && <Text style={styles.error}>⚠️ {error}</Text>}
      {entries.length === 0 && !refreshing && (
        <Text style={styles.empty}>Nenhum local monitorado ativo.</Text>
      )}
      {entries.map((entry) => (
        <AgroCard key={entry.location.id} entry={entry} />
      ))}
    </ScrollView>
  )
}

async function loadEntry(location: LocationItem): Promise<AgroEntry> {
  try {
    const [forecast, sprayWindow, rainfall, rainForecast, forecastComparison, vegetation] =
      await Promise.all([
      api.forecast(location.id).catch(() => null),
      api.sprayWindow(location.id).catch(() => null),
      api.rainfall(location.id).catch(() => null),
      // Always Open-Meteo (ADR-0020) — the general forecast above often
      // comes from CPTEC instead, which never has a numeric rain figure.
      api.rainForecast(location.id).catch(() => null),
      // Fase 2 (ADR-0082) — accumulated accuracy record, not live data.
      api.forecastComparison(location.id).catch(() => null),
      location.parent_location_id != null && location.boundary_geojson != null
        ? Promise.all(
            VEGETATION_INDICES.map((indexName) =>
              api.vegetationSeries(location.id, indexName).catch(() => null),
            ),
          ).then((items) => items.filter((item): item is VegetationSeries => item != null))
        : Promise.resolve([] as VegetationSeries[]),
      ])
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const { severe, light } = classifyFrostDays(
      forecast?.points ?? [],
      FROST_THRESHOLD_C,
      FROST_LIGHT_THRESHOLD_C,
    )
    const upcomingRain = (rainForecast?.points ?? []).filter((p) => new Date(p.time) >= today)
    const todayPoint = upcomingRain[0] ?? null

    const capeJkg = todayPoint?.cape_max_jkg ?? null
    const et0Mm = todayPoint?.evapotranspiration_mm ?? null
    const rainTodayMm = todayPoint?.precipitation_mm ?? null
    const tempMeanC = todayPoint?.temperature_mean_c ?? null
    const humidityMeanPercent = todayPoint?.humidity_mean_percent ?? null
    const vpdKpa =
      tempMeanC != null && humidityMeanPercent != null
        ? vaporPressureDeficitKpa(tempMeanC, humidityMeanPercent)
        : null

    return {
      location,
      severeFrostDays: severe,
      lightFrostDays: light,
      sprayWindow,
      rainfallTotalMm: rainfall ? rainfall.daily.reduce((sum, d) => sum + d.total_mm, 0) : null,
      rainfallDays: rainfall?.daily.length ?? 0,
      trafficability: rainfall
        ? evaluateTrafficability(rainfall.daily, upcomingRain, {
            requiredDryDays: TRAFFICABILITY_DRY_DAYS,
            rainThresholdMm: TRAFFICABILITY_RAIN_THRESHOLD_MM,
            lookaheadDays: TRAFFICABILITY_LOOKAHEAD_DAYS,
          })
        : null,
      capeJkg,
      capeLevel: capeJkg != null ? classifyCape(capeJkg) : null,
      windGustMaxKmh: todayPoint?.wind_gusts_max_kmh ?? null,
      waterBalanceMm:
        et0Mm != null && rainTodayMm != null ? waterBalanceMm(rainTodayMm, et0Mm) : null,
      gddC: tempMeanC != null ? growingDegreeDays(tempMeanC, GDD_BASE_TEMP_C) : null,
      diseaseRisk: classifyDiseaseRisk(humidityMeanPercent, tempMeanC, DISEASE_RISK_THRESHOLDS),
      vpdKpa,
      vpdLevel: vpdKpa != null ? classifyVpd(vpdKpa) : 'unknown',
      forecastComparison,
      vegetation,
      error:
        forecast == null && sprayWindow == null && rainfall == null
          ? 'Dados agro indisponíveis no momento'
          : null,
    }
  } catch {
    return {
      location,
      severeFrostDays: [],
      lightFrostDays: [],
      sprayWindow: null,
      rainfallTotalMm: null,
      rainfallDays: 0,
      trafficability: null,
      capeJkg: null,
      capeLevel: null,
      windGustMaxKmh: null,
      waterBalanceMm: null,
      gddC: null,
      diseaseRisk: 'unknown',
      vpdKpa: null,
      vpdLevel: 'unknown',
      forecastComparison: null,
      vegetation: [],
      error: 'Dados agro indisponíveis no momento',
    }
  }
}

function AgroCard({ entry }: { entry: AgroEntry }) {
  const hasFrost = entry.severeFrostDays.length > 0 || entry.lightFrostDays.length > 0

  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>
        {entry.location.parent_location_id != null ? '🌱 ' : ''}
        {entry.location.name}
      </Text>
      {entry.location.crop && <Text style={styles.crop}>{entry.location.crop}</Text>}

      {entry.error ? (
        <Text style={styles.row}>⚠️ {entry.error}</Text>
      ) : (
        <>
          {entry.severeFrostDays.length > 0 && (
            <Row warn text={`❄️ Geada forte: ${formatFrostDays(entry.severeFrostDays)}`} />
          )}
          {entry.lightFrostDays.length > 0 && (
            <Row warn text={`🌡️ Risco leve de geada: ${formatFrostDays(entry.lightFrostDays)}`} />
          )}
          {!hasFrost && <Row text="Sem risco de geada previsto." />}

          {entry.sprayWindow ? (
            <Row
              warn={entry.sprayWindow.safe === false}
              text={`🌬️ ${
                entry.sprayWindow.wind_kmh != null
                  ? `vento ${entry.sprayWindow.wind_kmh.toFixed(0)} km/h`
                  : 'vento indisponível'
              } — ${
                entry.sprayWindow.safe == null
                  ? 'não avaliável'
                  : entry.sprayWindow.safe
                    ? 'janela segura pra pulverizar'
                    : 'condições desfavoráveis'
              }`}
            />
          ) : (
            <Row text="Dado de vento indisponível." />
          )}

          {entry.rainfallTotalMm != null ? (
            <Row
              text={`🌧️ ${entry.rainfallTotalMm.toFixed(0)}mm acumulados (${entry.rainfallDays} dias)`}
            />
          ) : (
            <Row text="Histórico de chuva indisponível." />
          )}

          {entry.trafficability === 'trafficable' && (
            <Row text="🚜 Solo seco — favorável para manejo/colheita." />
          )}
          {entry.trafficability === 'not_trafficable' && (
            <Row warn text="🚜 Solo úmido ou chuva prevista — evitar manejo pesado." />
          )}
          {entry.trafficability == null && <Row text="🚜 Sem dado suficiente pra avaliar." />}

          {entry.waterBalanceMm != null && (
            <Row
              warn={entry.waterBalanceMm < 0}
              text={`💧 Balanço hídrico: ${entry.waterBalanceMm >= 0 ? '+' : ''}${entry.waterBalanceMm.toFixed(1)}mm hoje`}
            />
          )}
          {entry.gddC != null && <Row text={`🌱 ${entry.gddC.toFixed(1)} graus-dia hoje`} />}

          <Row
            warn={entry.diseaseRisk === 'high'}
            text={`🦠 Risco de doença: ${
              entry.diseaseRisk === 'high'
                ? 'elevado'
                : entry.diseaseRisk === 'low'
                  ? 'baixo'
                  : 'indisponível'
            }`}
          />
          <Row
            warn={entry.vpdLevel === 'high'}
            text={`VPD ${entry.vpdKpa != null ? `${entry.vpdKpa.toFixed(2)} kPa — ` : ''}${VPD_LABEL[entry.vpdLevel]}`}
          />

          {entry.capeJkg != null && entry.capeLevel != null && (
            <Row
              warn={entry.capeLevel === 'strong' || entry.capeLevel === 'extreme'}
              text={`🌩️ CAPE ${entry.capeJkg.toFixed(0)} J/kg — instabilidade ${CAPE_LABEL[entry.capeLevel]}`}
            />
          )}
          {entry.windGustMaxKmh != null && (
            <Row text={`💨 Rajada máxima prevista hoje: ${entry.windGustMaxKmh.toFixed(0)} km/h`} />
          )}

          <Row text={forecastComparisonSummary(entry.forecastComparison)} />

          {entry.location.parent_location_id != null && (
            <View style={styles.vegetationBlock}>
              <Text style={styles.vegetationTitle}>🛰️ Inteligência do talhão</Text>
              {entry.vegetation.length === 0 && (
                <Row text="Nenhuma imagem espectral válida disponível." />
              )}
              {entry.vegetation.map((series) => {
                const current = series.current
                if (!current) return null
                return (
                  <View key={series.index_name} style={styles.vegetationRow}>
                    <Text style={styles.row}>
                      {series.index_name.toUpperCase()} {current.value_mean.toFixed(3)} · qualidade{' '}
                      {current.quality} · {current.cloud_cover_percent.toFixed(0)}% nuvens
                    </Text>
                    {!current.reliable && (
                      <Text style={styles.rowWarn}>Imagem não confiável — excluída das análises.</Text>
                    )}
                    {series.anomaly.status === 'insufficient_history' ? (
                      <Text style={styles.row}>
                        Histórico {series.anomaly.baseline_count}/{series.anomaly.minimum_history}
                      </Text>
                    ) : (
                      <Text style={styles.row}>
                        Anomalia {series.anomaly.percent_difference?.toFixed(1) ?? '—'}%
                      </Text>
                    )}
                    {series.persistent_drop && (
                      <Text style={styles.rowWarn}>Queda persistente detectada.</Text>
                    )}
                  </View>
                )
              })}
            </View>
          )}
        </>
      )}
    </View>
  )
}

// Fase 2 (ADR-0082) — compact single-line summary for the mobile card;
// web/src/components/ForecastComparisonModal.tsx has the full per-model
// breakdown. Never names a "winner" below the minimum sample size.
function forecastComparisonSummary(comparison: ForecastComparison | null): string {
  if (!comparison || comparison.models.length === 0) {
    return '📊 Comparação de modelos: ainda sem dados suficientes.'
  }
  const reliable = comparison.models.filter((m) => m.has_enough_samples)
  if (reliable.length === 0) {
    return `📊 Comparação de modelos: acumulando amostras (mínimo ${comparison.min_sample_size}).`
  }
  const withMae = reliable.filter((m) => m.temperature_mae_c != null)
  if (withMae.length === 0) {
    return '📊 Comparação de modelos: amostra suficiente, mas sem erro de temperatura calculável.'
  }
  const best = withMae.reduce((a, b) => (b.temperature_mae_c! < a.temperature_mae_c! ? b : a))
  return `📊 Modelo mais preciso aqui: ${best.model} (erro médio de temperatura ${best.temperature_mae_c!.toFixed(1)}°C)`
}

function Row({ text, warn }: { text: string; warn?: boolean }) {
  return <Text style={[styles.row, warn && styles.rowWarn]}>{text}</Text>
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { padding: 16, paddingTop: 56, paddingBottom: 32 },
  title: { color: colors.ink, fontSize: 22, fontWeight: '700', marginBottom: 16 },
  error: { color: colors.red, marginBottom: 12 },
  empty: { color: colors.inkMute, fontSize: 14 },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  cardTitle: { color: colors.ink, fontSize: 16, fontWeight: '600' },
  crop: { color: colors.inkMute, fontSize: 12, marginTop: 2, marginBottom: 4 },
  row: { color: colors.inkDim, fontSize: 13, marginTop: 6 },
  rowWarn: { color: colors.orange },
  vegetationBlock: { marginTop: 12, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 8 },
  vegetationTitle: { color: colors.ink, fontSize: 14, fontWeight: '600' },
  vegetationRow: { marginTop: 4 },
})
