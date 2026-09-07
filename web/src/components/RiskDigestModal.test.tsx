import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { RiskDigestModal } from './RiskDigestModal'
import { ApiError, api } from '../api'
import type { RiskDigest } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      riskDigest: vi.fn(),
      recommendedActions: vi.fn(),
    },
  }
})

function emptyDigest(overrides: Partial<RiskDigest> = {}): RiskDigest {
  return {
    location_id: 'loc-1',
    generated_at: '2026-09-07T12:00:00Z',
    storm: null,
    ndvi: null,
    deforestation: null,
    frost_last_alert: null,
    dry_spell_last_alert: null,
    soil_moisture: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.mocked(api.recommendedActions).mockResolvedValue([])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RiskDigestModal (Fase 3-A — risco consolidado)', () => {
  test('shows a loading hint, then an honest empty state when no signal has been computed', async () => {
    vi.mocked(api.riskDigest).mockResolvedValue(emptyDigest())

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    expect(screen.getByText(/carregando/i)).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByText(/Nenhum sinal calculado ainda/)).toBeInTheDocument(),
    )
  })

  test('shows the storm signal once resolved', async () => {
    vi.mocked(api.riskDigest).mockResolvedValue(
      emptyDigest({
        storm: {
          id: 's1',
          location_id: 'loc-1',
          storm_cell_id: null,
          severity: 'orange',
          rain_risk: 0.6,
          wind_risk: 0.3,
          hail_risk: 0.1,
          lightning_risk: 0.2,
          storm_distance_km: 12,
          storm_speed_kmh: 20,
          eta_minutes: 30,
          computed_at: '2026-09-07T11:55:00Z',
          is_mock: true,
          experimental: true,
          ai_summary: null,
        },
      }),
    )

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText(/Tempestade — Alto/)).toBeInTheDocument())
    expect(screen.getByText(/chega em 30 min/)).toBeInTheDocument()
  })

  test('labels frost/dry-spell as last alert, not a current risk level', async () => {
    vi.mocked(api.riskDigest).mockResolvedValue(
      emptyDigest({
        frost_last_alert: {
          occurred_at: '2026-09-06T04:00:00Z',
          level: 'red',
          title: 'Geada severa prevista',
          message: 'Temperatura mínima abaixo de 0°C.',
        },
      }),
    )

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText(/Geada severa prevista/)).toBeInTheDocument())
    expect(screen.getByText(/histórico, não é o risco agora/)).toBeInTheDocument()
  })

  test('surfaces the ApiError message instead of the panel on failure', async () => {
    vi.mocked(api.riskDigest).mockRejectedValue(new ApiError(500, 'Falha ao carregar'))

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText(/Falha ao carregar/)).toBeInTheDocument())
  })

  test('clicking "Fechar" calls onClose', async () => {
    vi.mocked(api.riskDigest).mockResolvedValue(emptyDigest())
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={onClose} />)
    await waitFor(() => expect(screen.getByText(/Nenhum sinal calculado ainda/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  test('shows recommended actions alongside the risk signals (Fase 5, ADR-0089)', async () => {
    vi.mocked(api.riskDigest).mockResolvedValue(emptyDigest())
    vi.mocked(api.recommendedActions).mockResolvedValue([
      {
        id: 'rec-1',
        location_id: 'loc-1',
        rule_key: 'frost_severe_irrigation',
        title: 'Geada severa prevista',
        message: 'Considere irrigação por aspersão ou cobertura das plantas.',
        level: 'red',
        alert_id: null,
        created_at: '2026-09-07T12:00:00Z',
      },
    ])

    render(<RiskDigestModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText('Geada severa prevista')).toBeInTheDocument())
    expect(
      screen.getByText('Considere irrigação por aspersão ou cobertura das plantas.'),
    ).toBeInTheDocument()
  })
})
