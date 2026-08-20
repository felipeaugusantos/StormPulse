import { useEffect, useState } from 'react'
import { cardinalDirection, convectiveIntensity, timeAgo } from '../format'
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
}

export function SatelliteWatchRow({ watch, onSelect }: Props) {
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
          Nuvem em formação · {timeAgo(watch.detected_at)}
          {watch.speed_kmh != null && watch.direction_deg != null
            ? ` · movendo para ${cardinalDirection(watch.direction_deg)} a ${watch.speed_kmh.toFixed(0)} km/h`
            : ''}
        </div>
        <div className="sub">📍 {place}</div>
      </div>
    </div>
  )
}
