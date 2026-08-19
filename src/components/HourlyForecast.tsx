import type { HourlyPoint } from '../api/openMeteo'
import { weatherInfo } from '../lib/weatherCodes'
import { formatHour } from '../lib/format'

interface Props {
  hourly: HourlyPoint[]
}

export function HourlyForecast({ hourly }: Props) {
  const maxTemp = Math.max(...hourly.map((h) => h.temperature))
  const minTemp = Math.min(...hourly.map((h) => h.temperature))
  const range = Math.max(1, maxTemp - minTemp)

  return (
    <section className="panel">
      <h3 className="panel-title">Próximas 24 horas</h3>
      <div className="hourly-scroll">
        {hourly.map((h, i) => {
          const info = weatherInfo(h.weatherCode)
          const heightPct = 20 + ((h.temperature - minTemp) / range) * 60
          return (
            <div className="hour" key={h.time}>
              <span className="hour-time">{i === 0 ? 'Agora' : formatHour(h.time)}</span>
              <span className="hour-icon" aria-hidden>{info.icon}</span>
              <div className="hour-bar-wrap" title={`${Math.round(h.temperature)}°`}>
                <div className="hour-bar" style={{ height: `${heightPct}%` }} />
              </div>
              <span className="hour-temp">{Math.round(h.temperature)}°</span>
              <span
                className={`hour-precip ${h.precipitationProbability >= 50 ? 'wet' : ''}`}
              >
                💧{h.precipitationProbability}%
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
