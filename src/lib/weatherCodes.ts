// WMO weather interpretation codes → label + emoji icon.
// https://open-meteo.com/en/docs (see "WMO Weather interpretation codes")

export interface WeatherInfo {
  label: string
  icon: string
  /** rough theme bucket used for background gradients */
  theme: 'clear' | 'cloud' | 'rain' | 'snow' | 'storm' | 'fog'
}

const CODES: Record<number, WeatherInfo> = {
  0: { label: 'Céu limpo', icon: '☀️', theme: 'clear' },
  1: { label: 'Predominantemente limpo', icon: '🌤️', theme: 'clear' },
  2: { label: 'Parcialmente nublado', icon: '⛅', theme: 'cloud' },
  3: { label: 'Nublado', icon: '☁️', theme: 'cloud' },
  45: { label: 'Névoa', icon: '🌫️', theme: 'fog' },
  48: { label: 'Névoa com geada', icon: '🌫️', theme: 'fog' },
  51: { label: 'Garoa leve', icon: '🌦️', theme: 'rain' },
  53: { label: 'Garoa moderada', icon: '🌦️', theme: 'rain' },
  55: { label: 'Garoa intensa', icon: '🌧️', theme: 'rain' },
  56: { label: 'Garoa congelante leve', icon: '🌧️', theme: 'rain' },
  57: { label: 'Garoa congelante intensa', icon: '🌧️', theme: 'rain' },
  61: { label: 'Chuva fraca', icon: '🌧️', theme: 'rain' },
  63: { label: 'Chuva moderada', icon: '🌧️', theme: 'rain' },
  65: { label: 'Chuva forte', icon: '🌧️', theme: 'rain' },
  66: { label: 'Chuva congelante leve', icon: '🌧️', theme: 'rain' },
  67: { label: 'Chuva congelante forte', icon: '🌧️', theme: 'rain' },
  71: { label: 'Neve fraca', icon: '🌨️', theme: 'snow' },
  73: { label: 'Neve moderada', icon: '🌨️', theme: 'snow' },
  75: { label: 'Neve forte', icon: '❄️', theme: 'snow' },
  77: { label: 'Grãos de neve', icon: '❄️', theme: 'snow' },
  80: { label: 'Pancadas de chuva leves', icon: '🌦️', theme: 'rain' },
  81: { label: 'Pancadas de chuva moderadas', icon: '🌧️', theme: 'rain' },
  82: { label: 'Pancadas de chuva violentas', icon: '⛈️', theme: 'storm' },
  85: { label: 'Pancadas de neve leves', icon: '🌨️', theme: 'snow' },
  86: { label: 'Pancadas de neve fortes', icon: '❄️', theme: 'snow' },
  95: { label: 'Tempestade', icon: '⛈️', theme: 'storm' },
  96: { label: 'Tempestade com granizo leve', icon: '⛈️', theme: 'storm' },
  99: { label: 'Tempestade com granizo forte', icon: '⛈️', theme: 'storm' },
}

const UNKNOWN: WeatherInfo = { label: 'Desconhecido', icon: '❓', theme: 'cloud' }

export function weatherInfo(code: number): WeatherInfo {
  return CODES[code] ?? UNKNOWN
}
