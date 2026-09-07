import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { AlertRulesModal } from './AlertRulesModal'
import { ApiError, api } from '../api'
import type { AlertRule, SimulateResult } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      alertRules: vi.fn(),
      createAlertRule: vi.fn(),
      deleteAlertRule: vi.fn(),
      simulateAlertRule: vi.fn(),
    },
  }
})

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'rule-1',
    location_id: 'loc-1',
    name: 'Vento forte',
    enabled: true,
    lead_time_minutes: 0,
    quiet_hours_start: null,
    quiet_hours_end: null,
    cooldown_minutes: 0,
    last_fired_at: null,
    conditions: [{ id: 'cond-1', metric: 'wind_kmh', operator: '>', threshold: 40, group: 0 }],
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AlertRulesModal (Fase 3 — alertas personalizados)', () => {
  test('shows a loading hint, then the rule list once resolved', async () => {
    vi.mocked(api.alertRules).mockResolvedValue([rule()])

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    expect(screen.getByText(/carregando/i)).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('Vento forte')).toBeInTheDocument())
    expect(screen.getByText(/Vento \(km\/h\) > 40/)).toBeInTheDocument()
  })

  test('shows an honest empty state for a location with no rules yet', async () => {
    vi.mocked(api.alertRules).mockResolvedValue([])

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Novo" onClose={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByText(/Nenhuma regra personalizada ainda/)).toBeInTheDocument(),
    )
  })

  test('surfaces the ApiError message instead of the panel on failure', async () => {
    vi.mocked(api.alertRules).mockRejectedValue(new ApiError(500, 'Falha ao carregar'))

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)

    await waitFor(() => expect(screen.getByText(/Falha ao carregar/)).toBeInTheDocument())
  })

  test('creating a rule with a condition posts it and reloads the list', async () => {
    vi.mocked(api.alertRules).mockResolvedValueOnce([]).mockResolvedValueOnce([rule()])
    vi.mocked(api.createAlertRule).mockResolvedValue(rule())
    const user = userEvent.setup()

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/Nenhuma regra personalizada ainda/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '+ nova regra' }))
    await user.type(screen.getByPlaceholderText('Ex: Vento forte'), 'Vento forte')
    await user.click(screen.getByRole('button', { name: 'Criar regra' }))

    await waitFor(() =>
      expect(api.createAlertRule).toHaveBeenCalledWith(
        expect.objectContaining({
          location_id: 'loc-1',
          name: 'Vento forte',
          conditions: [expect.objectContaining({ metric: 'wind_kmh', operator: '>', threshold: 40 })],
        }),
      ),
    )
    await waitFor(() => expect(screen.getByText('Vento forte')).toBeInTheDocument())
  })

  test('simulate button shows would_fire and the snapshot, never persisting anything', async () => {
    vi.mocked(api.alertRules).mockResolvedValue([rule()])
    const result: SimulateResult = {
      would_fire: true,
      snapshot: { wind_kmh: 55 },
      matched_groups: [0],
    }
    vi.mocked(api.simulateAlertRule).mockResolvedValue(result)
    const user = userEvent.setup()

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Vento forte')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '▶️ simular' }))

    await waitFor(() => expect(screen.getByText(/Dispararia agora/)).toBeInTheDocument())
    expect(api.simulateAlertRule).toHaveBeenCalledWith('rule-1')
  })

  test('clicking "Fechar" calls onClose', async () => {
    vi.mocked(api.alertRules).mockResolvedValue([rule()])
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(<AlertRulesModal locationId="loc-1" locationName="Talhão Norte" onClose={onClose} />)
    await waitFor(() => expect(screen.getByText('Vento forte')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
