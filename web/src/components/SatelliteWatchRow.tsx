import { useEffect, useState } from 'react'
import { cardinalDirection, convectiveIntensity, kelvinToCelsius, timeAgo } from '../format'
import { reverseGeocodeCity } from '../geocode'
import type { ConvectiveWatch } from '../types'

function useCityName(latitude: number, longitude: number): string | null {
  const [city, setCity] = useState<string | null>(null)
  useEffect(() => {
    setCity(null)
    reverseGeocodeCity(latitude, longitude, setCity)
  }, [latitude, longitude])
  return city
}

interface Props {
  watch: ConvectiveWatch
  /** Present → the row is clickable and centers the map on the watch. */
  onSelect?: (latitude: number, longitude: number) => void
  /** "chegada estimada em X min em <local>" — computed by the caller from
   * ``estimateStormEta`` (FASE 25, ADR-0021), against the nearest monitored
   * location this cell is actually heading toward. Omitted when the cell
   * isn't heading anywhere being watched. */
  etaLabel?: string | null
}

export function SatelliteWatchRow({ watch, onSelect, etaLabel }: Props) {
  const intensity = convectiveIntensity(watch.min_brightness_temp_k)
  const city = useCityName(watch.latitude, watch.longitude)
  const place = city ?? `${watch.latitude.toFixed(2)}, ${watch.longitude.toFixed(2)}`

  return (
    <div
      className={`row${onSelect ? ' clickable' : ''}`}
      onClick={onSelect ? () => onSelect(watch.latitude, watch.longitude) : undefined}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
    >
      <span className={`badge ${intensity.className}`}>{intensity.label}</span>
      <div className="grow">
        <div>
          Nuvem em formação · {kelvinToCelsius(watch.min_brightness_temp_k).toFixed(0)}°C no topo
          · {timeAgo(watch.detected_at)}
          {watch.speed_kmh != null && watch.direction_deg != null
            ? ` · movendo para ${cardinalDirection(watch.direction_deg)} a ${watch.speed_kmh.toFixed(0)} km/h`
            : ''}
        </div>
        <div className="sub">📍 {place}</div>
        {etaLabel && <div className="sub eta-warn">⏱️ {etaLabel}</div>}
      </div>
    </div>
  )
}
