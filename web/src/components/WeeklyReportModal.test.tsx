import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { WeeklyReportModal } from './WeeklyReportModal'
import { ApiError, api } from '../api'
import type { WeeklyReport } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      weeklyReport: vi.fn(),
      ndviImage: vi.fn(),
      weeklyReportPdf: vi.fn(),
    },
  }
})

function baseReport(overrides: Partial<WeeklyReport> = {}): WeeklyReport {
  return {
    location_id: 'loc-1',
    location_name: 'Talhão Norte',
    crop: 'soja',
    area_ha: 12.5,
    period_start: '2026-08-29T00:00:00Z',
    period_end: '2026-09-05T00:00:00Z',
    rainfall_total_mm: 42.3,
    dry_days_count: 2,
    alerts: [],
    ndvi_readings: [],
    deforestation: null,
    soil_moisture: null,
    generated_at: '2026-09-05T12:00:00Z',
    ai_summary: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(api.ndviImage).mockRejectedValue(new ApiError(404, 'sem imagem'))
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WeeklyReportModal (Fase 1 — cobertura de testes de fluxos críticos)', () => {
  test('shows a loading hint, then the report once it resolves', async () => {
    vi.mocked(api.weeklyReport).mockResolvedValue(baseReport())

    render(
      <WeeklyReportModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )

    expect(screen.getByText(/carregando/i)).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('42.3mm')).toBeInTheDocument())
    expect(screen.getByText('chuva acumulada')).toBeInTheDocument()
    expect(screen.getByText('2/7')).toBeInTheDocument()
    expect(screen.getByText('soja')).toBeInTheDocument()
  })

  test('surfaces the ApiError message instead of the report on failure', async () => {
    vi.mocked(api.weeklyReport).mockRejectedValue(new ApiError(500, 'Falha ao gerar relatório'))

    render(
      <WeeklyReportModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )

    await waitFor(() =>
      expect(screen.getByText(/Falha ao gerar relatório/)).toBeInTheDocument(),
    )
    expect(screen.queryByText('chuva acumulada')).not.toBeInTheDocument()
  })

  test('clicking "Fechar" calls onClose', async () => {
    vi.mocked(api.weeklyReport).mockResolvedValue(baseReport())
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(<WeeklyReportModal locationId="loc-1" locationName="Talhão Norte" onClose={onClose} />)
    await waitFor(() => expect(screen.getByText('42.3mm')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  test('"Baixar PDF" calls the PDF endpoint and shows a busy state meanwhile', async () => {
    vi.mocked(api.weeklyReport).mockResolvedValue(baseReport())
    let resolvePdf: (blob: Blob) => void = () => {}
    vi.mocked(api.weeklyReportPdf).mockReturnValue(
      new Promise((resolve) => {
        resolvePdf = resolve
      }),
    )
    // jsdom has no real object URL registry — only the call matters here.
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() })
    const user = userEvent.setup()

    render(
      <WeeklyReportModal locationId="loc-1" locationName="Talhão Norte" onClose={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText('42.3mm')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /Baixar PDF/ }))
    expect(screen.getByRole('button', { name: /Gerando/ })).toBeDisabled()
    expect(api.weeklyReportPdf).toHaveBeenCalledWith('loc-1')

    resolvePdf(new Blob(['%PDF'], { type: 'application/pdf' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Baixar PDF/ })).not.toBeDisabled(),
    )
  })
})
