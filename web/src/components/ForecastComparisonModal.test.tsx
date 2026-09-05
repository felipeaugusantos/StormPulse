import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ForecastComparisonModal } from './ForecastComparisonModal'
import { ApiError, api } from '../api'
import type { ForecastComparison, ModelMetrics } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      forecastComparison: vi.fn(),
    },
  }
})

function modelMetrics(overrides: Partial<ModelMetrics> = {}): ModelMetrics {
  return {
    model: 'ecmwf_ifs025',
    sample_count: 25,
    has_enough_samples: true,
    temperature_mae_c: 1.5,
    precipitation: { bias_mm: -2.0, mae_mm: 4.0, sample_count: 25 },
    wind_mae_kmh: 3.2,
    rain_hit_rate: 0.8,
    brier_score: 0.12,
    ...overrides,
  }
}

function comparison(overrides: Partial<ForecastComparison> = {}): ForecastComparison {
  return {
    location_id: 'loc-1',
    min_sample_size: 20,
    models: [modelMetrics()],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ForecastComparisonModal (Fase 2 — comparação de modelos)', () => {
  test('shows a loading hint, then the metrics once resolved', async () => {
    vi.mocked(api.forecastComparison).mockResolvedValue(comparison())

    render(
      <ForecastComparisonModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )

    expect(screen.getByText(/carregando/i)).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('ECMWF (IFS)')).toBeInTheDocument())
    expect(screen.getByText('1.5°C')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
    expect(screen.getByText('amostra suficiente')).toBeInTheDocument()
  })

  test('flags a model below the minimum sample size instead of hiding it', async () => {
    vi.mocked(api.forecastComparison).mockResolvedValue(
      comparison({ models: [modelMetrics({ sample_count: 4, has_enough_samples: false })] }),
    )

    render(
      <ForecastComparisonModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )

    await waitFor(() => expect(screen.getByText('4/20 amostras')).toBeInTheDocument())
  })

  test('shows an honest empty state for a location with no models yet', async () => {
    vi.mocked(api.forecastComparison).mockResolvedValue(comparison({ models: [] }))

    render(
      <ForecastComparisonModal locationId="loc-1" locationName="Talhão Novo" onClose={vi.fn()} />,
    )

    await waitFor(() =>
      expect(screen.getByText(/Nenhum modelo tem previsões confirmadas/)).toBeInTheDocument(),
    )
  })

  test('surfaces the ApiError message instead of the panel on failure', async () => {
    vi.mocked(api.forecastComparison).mockRejectedValue(new ApiError(500, 'Falha ao comparar'))

    render(
      <ForecastComparisonModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )

    await waitFor(() => expect(screen.getByText(/Falha ao comparar/)).toBeInTheDocument())
  })

  test('clicking "Fechar" calls onClose', async () => {
    vi.mocked(api.forecastComparison).mockResolvedValue(comparison())
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(
      <ForecastComparisonModal locationId="loc-1" locationName="Talhão Norte" onClose={onClose} />,
    )
    await waitFor(() => expect(screen.getByText('ECMWF (IFS)')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
