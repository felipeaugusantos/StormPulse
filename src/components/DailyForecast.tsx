import type { DailyPoint } from '../api/openMeteo'
import { weatherInfo } from '../lib/weatherCodes'
import { formatWeekday } from '../lib/format'

interface Props {
  daily: DailyPoint[]
}

export function DailyForecast({ daily }: Props) {
  const globalMin = Math.min(...daily.map((d) => d.tempMin))
  const globalMax = Math.max(...daily.map((d) => d.tempMax))
  const span = Math.max(1, globalMax - globalMin)

  return (
    <section className="panel">
      <h3 className="panel-title">7 dias</h3>
      <div className="daily-list">
        {daily.map((d, i) => {
          const info = weatherInfo(d.weatherCode)
          const left = ((d.tempMin - globalMin) / span) * 100
          const width = ((d.tempMax - d.tempMin) / span) * 100
          return (
            <div className="day" key={d.date}>
              <span className="day-name">{i === 0 ? 'Hoje' : formatWeekday(d.date)}</span>
              <span className="day-icon" aria-hidden title={info.label}>{info.icon}</span>
              <span className="day-precip">
                {d.precipitationProbabilityMax > 0 ? `💧${d.precipitationProbabilityMax}%` : ''}
              </span>
              <span className="day-min">{Math.round(d.tempMin)}°</span>
              <div className="day-track">
                <div
                  className="day-range"
                  style={{ left: `${left}%`, width: `${Math.max(8, width)}%` }}
                />
              </div>
              <span className="day-max">{Math.round(d.tempMax)}°</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
