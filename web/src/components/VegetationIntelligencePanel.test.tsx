import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { api } from '../api'
import type { LocationItem, VegetationSeries } from '../types'
import { VegetationIntelligencePanel } from './VegetationIntelligencePanel'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      ...actual.api,
      vegetationSeries: vi.fn(),
      vegetationComparison: vi.fn(),
      vegetationImage: vi.fn(),
      vegetationCsv: vi.fn(),
    },
  }
})

const plot = {
  id: 'plot-1',
  name: 'Talhão Norte',
  kind: 'other',
  latitude: -21.19,
  longitude: -47.79,
  radius_km: 1,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  alert_preferences: [],
  parent_location_id: 'farm-1',
  crop: 'soja',
  soil_type: null,
  boundary_geojson: '{"type":"Polygon","coordinates":[]}',
  color: null,
  area_ha: 12,
} satisfies LocationItem

const cloudySeries: VegetationSeries = {
  location_id: plot.id,
  index_name: 'ndvi',
  current: {
    id: 'reading-1',
    observed_at: '2026-09-01T00:00:00Z',
    index_name: 'ndvi',
    value_mean: 0.41,
    source_name: 'Copernicus Sentinel Hub',
    valid_pixel_percent: 45,
    cloud_cover_percent: 55,
    quality: 'low',
    reliable: false,
    vigor_zones: [],
    is_mock: false,
  },
  series: [],
  anomaly: {
    status: 'insufficient_history',
    minimum_history: 5,
    baseline_count: 2,
    baseline_mean: null,
    difference: null,
    percent_difference: null,
    z_score: null,
  },
  persistent_drop: false,
}

describe('VegetationIntelligencePanel (Fase 5)', () => {
  beforeEach(() => {
    vi.mocked(api.vegetationSeries).mockResolvedValue(cloudySeries)
    vi.mocked(api.vegetationComparison).mockRejectedValue(new Error('sem duas cenas confiáveis'))
  })

  test('identifica a fonte, data, índice e qualidade e não confia em cena com nuvens', async () => {
    render(<VegetationIntelligencePanel locations={[plot]} />)

    await waitFor(() => expect(screen.getByText('Copernicus Sentinel Hub')).toBeInTheDocument())
    expect(screen.getByText('NDVI 0.410')).toBeInTheDocument()
    expect(screen.getByText('qualidade baixa')).toBeInTheDocument()
    expect(screen.getByText('55.0% nuvens/sem dado')).toBeInTheDocument()
    expect(screen.getByText(/não confiável para análise/i)).toBeInTheDocument()
    expect(screen.getByText(/2\/5 imagens confiáveis/i)).toBeInTheDocument()
    expect(api.vegetationImage).not.toHaveBeenCalled()
  })
})
