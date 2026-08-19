// Thin client for the Open-Meteo APIs. No API key required.
// Docs: https://open-meteo.com/en/docs

export interface GeoResult {
  id: number
  name: string
  latitude: number
  longitude: number
  country: string
  countryCode: string
  admin1?: string
  timezone: string
}

export interface CurrentWeather {
  time: string
  temperature: number
  apparentTemperature: number
  humidity: number
  precipitation: number
  weatherCode: number
  windSpeed: number
  windGusts: number
  windDirection: number
  pressure: number
  cloudCover: number
  isDay: boolean
}

export interface HourlyPoint {
  time: string
  temperature: number
  precipitationProbability: number
  precipitation: number
  weatherCode: number
  windGusts: number
}

export interface DailyPoint {
  date: string
  weatherCode: number
  tempMax: number
  tempMin: number
  precipitationSum: number
  precipitationProbabilityMax: number
  windGustsMax: number
  sunrise: string
  sunset: string
  uvIndexMax: number
}

export interface Forecast {
  place: GeoResult
  current: CurrentWeather
  hourly: HourlyPoint[]
  daily: DailyPoint[]
  fetchedAt: number
}

const GEO_URL = 'https://geocoding-api.open-meteo.com/v1/search'
const FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'

export async function searchPlaces(query: string): Promise<GeoResult[]> {
  const url = new URL(GEO_URL)
  url.searchParams.set('name', query)
  url.searchParams.set('count', '6')
  url.searchParams.set('language', 'pt')
  url.searchParams.set('format', 'json')

  const res = await fetch(url)
  if (!res.ok) throw new Error(`Falha na busca de locais (HTTP ${res.status})`)
  const data = await res.json()
  if (!data.results) return []

  return data.results.map(
    (r: Record<string, unknown>): GeoResult => ({
      id: r.id as number,
      name: r.name as string,
      latitude: r.latitude as number,
      longitude: r.longitude as number,
      country: (r.country as string) ?? '',
      countryCode: (r.country_code as string) ?? '',
      admin1: r.admin1 as string | undefined,
      timezone: (r.timezone as string) ?? 'auto',
    }),
  )
}

export async function fetchForecast(place: GeoResult): Promise<Forecast> {
  const url = new URL(FORECAST_URL)
  url.searchParams.set('latitude', String(place.latitude))
  url.searchParams.set('longitude', String(place.longitude))
  url.searchParams.set('timezone', 'auto')
  url.searchParams.set(
    'current',
    [
      'temperature_2m',
      'apparent_temperature',
      'relative_humidity_2m',
      'precipitation',
      'weather_code',
      'wind_speed_10m',
      'wind_gusts_10m',
      'wind_direction_10m',
      'surface_pressure',
      'cloud_cover',
      'is_day',
    ].join(','),
  )
  url.searchParams.set(
    'hourly',
    [
      'temperature_2m',
      'precipitation_probability',
      'precipitation',
      'weather_code',
      'wind_gusts_10m',
    ].join(','),
  )
  url.searchParams.set(
    'daily',
    [
      'weather_code',
      'temperature_2m_max',
      'temperature_2m_min',
      'precipitation_sum',
      'precipitation_probability_max',
      'wind_gusts_10m_max',
      'sunrise',
      'sunset',
      'uv_index_max',
    ].join(','),
  )
  url.searchParams.set('forecast_days', '7')

  const res = await fetch(url)
  if (!res.ok) throw new Error(`Falha ao carregar a previsão (HTTP ${res.status})`)
  const d = await res.json()

  const c = d.current
  const current: CurrentWeather = {
    time: c.time,
    temperature: c.temperature_2m,
    apparentTemperature: c.apparent_temperature,
    humidity: c.relative_humidity_2m,
    precipitation: c.precipitation,
    weatherCode: c.weather_code,
    windSpeed: c.wind_speed_10m,
    windGusts: c.wind_gusts_10m,
    windDirection: c.wind_direction_10m,
    pressure: c.surface_pressure,
    cloudCover: c.cloud_cover,
    isDay: c.is_day === 1,
  }

  // Only keep the next 24 hourly points from "now".
  const nowIdx = nearestHourIndex(d.hourly.time)
  const hourly: HourlyPoint[] = d.hourly.time
    .slice(nowIdx, nowIdx + 24)
    .map((time: string, i: number) => {
      const idx = nowIdx + i
      return {
        time,
        temperature: d.hourly.temperature_2m[idx],
        precipitationProbability: d.hourly.precipitation_probability[idx] ?? 0,
        precipitation: d.hourly.precipitation[idx] ?? 0,
        weatherCode: d.hourly.weather_code[idx],
        windGusts: d.hourly.wind_gusts_10m[idx],
      }
    })

  const daily: DailyPoint[] = d.daily.time.map((date: string, i: number) => ({
    date,
    weatherCode: d.daily.weather_code[i],
    tempMax: d.daily.temperature_2m_max[i],
    tempMin: d.daily.temperature_2m_min[i],
    precipitationSum: d.daily.precipitation_sum[i],
    precipitationProbabilityMax: d.daily.precipitation_probability_max[i] ?? 0,
    windGustsMax: d.daily.wind_gusts_10m_max[i],
    sunrise: d.daily.sunrise[i],
    sunset: d.daily.sunset[i],
    uvIndexMax: d.daily.uv_index_max[i],
  }))

  return { place, current, hourly, daily, fetchedAt: Date.now() }
}

function nearestHourIndex(times: string[]): number {
  const now = Date.now()
  let best = 0
  let bestDiff = Infinity
  for (let i = 0; i < times.length; i++) {
    const diff = Math.abs(new Date(times[i]).getTime() - now)
    if (diff < bestDiff) {
      bestDiff = diff
      best = i
    }
  }
  return best
}
