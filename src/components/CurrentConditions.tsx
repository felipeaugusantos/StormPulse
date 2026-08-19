import type { CurrentWeather, GeoResult } from '../api/openMeteo'
import { weatherInfo } from '../lib/weatherCodes'
import { placeLabel, windDirectionLabel } from '../lib/format'

interface Props {
  place: GeoResult
  current: CurrentWeather
}

export function CurrentConditions({ place, current }: Props) {
  const info = weatherInfo(current.weatherCode)
  const metrics = [
    { label: 'Sensação', value: `${Math.round(current.apparentTemperature)}°`, icon: '🌡️' },
    { label: 'Umidade', value: `${current.humidity}%`, icon: '💧' },
    {
      label: 'Vento',
      value: `${Math.round(current.windSpeed)} km/h ${windDirectionLabel(current.windDirection)}`,
      icon: '🧭',
    },
    { label: 'Rajadas', value: `${Math.round(current.windGusts)} km/h`, icon: '💨' },
    { label: 'Pressão', value: `${Math.round(current.pressure)} hPa`, icon: '📊' },
    { label: 'Nuvens', value: `${current.cloudCover}%`, icon: '☁️' },
  ]

  return (
    <section className="current">
      <div className="current-main">
        <div className="current-icon" aria-hidden>{info.icon}</div>
        <div className="current-temp-block">
          <div className="current-temp">{Math.round(current.temperature)}°</div>
          <div className="current-desc">{info.label}</div>
          <div className="current-place">
            {placeLabel(place.name, place.admin1, place.country)}
          </div>
        </div>
      </div>

      <div className="metric-grid">
        {metrics.map((m) => (
          <div className="metric" key={m.label}>
            <span className="metric-icon" aria-hidden>{m.icon}</span>
            <span className="metric-value">{m.value}</span>
            <span className="metric-label">{m.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
