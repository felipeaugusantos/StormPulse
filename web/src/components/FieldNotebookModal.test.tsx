import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { FieldNotebookModal } from './FieldNotebookModal'
import { ApiError, api } from '../api'
import type { FieldOccurrence, FieldTask } from '../types'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      fieldTimeline: vi.fn(),
      fieldOccurrences: vi.fn(),
      fieldInspections: vi.fn(),
      fieldTasks: vi.fn(),
      createFieldOccurrence: vi.fn(),
      createFieldInspection: vi.fn(),
      createFieldTask: vi.fn(),
      updateFieldTask: vi.fn(),
      uploadFieldPhoto: vi.fn(),
    },
  }
})

function occurrence(overrides: Partial<FieldOccurrence> = {}): FieldOccurrence {
  return {
    id: 'occ-1',
    location_id: 'loc-1',
    alert_id: null,
    recommended_action_id: null,
    category: 'praga',
    description: 'Lagarta encontrada.',
    latitude: -21.18,
    longitude: -47.81,
    status: 'open',
    reported_by: 'user-1',
    reported_at: '2026-09-07T12:00:00Z',
    version: 1,
    ...overrides,
  }
}

function task(overrides: Partial<FieldTask> = {}): FieldTask {
  return {
    id: 'task-1',
    location_id: 'loc-1',
    occurrence_id: null,
    alert_id: null,
    recommended_action_id: null,
    title: 'Aplicar defensivo',
    description: null,
    assigned_to: null,
    due_at: null,
    status: 'pending',
    completed_by: null,
    completed_at: null,
    version: 1,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.mocked(api.fieldTimeline).mockResolvedValue([])
  vi.mocked(api.fieldOccurrences).mockResolvedValue([])
  vi.mocked(api.fieldInspections).mockResolvedValue([])
  vi.mocked(api.fieldTasks).mockResolvedValue([])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('FieldNotebookModal (Fase 6 — Caderno de Campo)', () => {
  test('shows a loading hint, then an honest empty state', async () => {
    render(
      <FieldNotebookModal
        locationId="loc-1"
        locationName="Talhão Norte"
        latitude={-21.18}
        longitude={-47.81}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText(/carregando/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/Nenhum evento registrado/)).toBeInTheDocument())
  })

  test('creating an occurrence posts it and shows it in the list', async () => {
    vi.mocked(api.createFieldOccurrence).mockResolvedValue(occurrence())
    const user = userEvent.setup()

    render(
      <FieldNotebookModal
        locationId="loc-1"
        locationName="Talhão Norte"
        latitude={-21.18}
        longitude={-47.81}
        onClose={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByText(/Nenhum evento registrado/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Ocorrências' }))
    await user.type(screen.getByPlaceholderText(/Categoria/), 'praga')
    await user.type(screen.getByPlaceholderText(/O que foi observado/), 'Lagarta encontrada.')
    await user.click(screen.getByRole('button', { name: '+ Registrar ocorrência' }))

    await waitFor(() =>
      expect(api.createFieldOccurrence).toHaveBeenCalledWith(
        'loc-1',
        expect.objectContaining({ category: 'praga', description: 'Lagarta encontrada.' }),
      ),
    )
    await waitFor(() => expect(screen.getByText(/praga — aberta/)).toBeInTheDocument())
  })

  test('marking a task done sends its current version (optimistic concurrency)', async () => {
    vi.mocked(api.fieldTasks).mockResolvedValue([task()])
    vi.mocked(api.updateFieldTask).mockResolvedValue(task({ status: 'done', version: 2 }))
    const user = userEvent.setup()

    render(
      <FieldNotebookModal
        locationId="loc-1"
        locationName="Talhão Norte"
        latitude={-21.18}
        longitude={-47.81}
        onClose={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByText(/Nenhum evento registrado/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Tarefas' }))
    await waitFor(() => expect(screen.getByText('Aplicar defensivo')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Marcar como concluída' }))

    await waitFor(() =>
      expect(api.updateFieldTask).toHaveBeenCalledWith('task-1', {
        base_version: 1,
        status: 'done',
      }),
    )
    await waitFor(() => expect(screen.getByText(/Status: concluída/)).toBeInTheDocument())
  })

  test('surfaces the ApiError message instead of the panel on failure', async () => {
    vi.mocked(api.fieldTimeline).mockRejectedValue(new ApiError(500, 'Falha ao carregar'))

    render(
      <FieldNotebookModal
        locationId="loc-1"
        locationName="Talhão Norte"
        latitude={-21.18}
        longitude={-47.81}
        onClose={vi.fn()}
      />,
    )

    await waitFor(() => expect(screen.getByText(/Falha ao carregar/)).toBeInTheDocument())
  })

  test('clicking "Fechar" calls onClose', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()

    render(
      <FieldNotebookModal
        locationId="loc-1"
        locationName="Talhão Norte"
        latitude={-21.18}
        longitude={-47.81}
        onClose={onClose}
      />,
    )
    await waitFor(() => expect(screen.getByText(/Nenhum evento registrado/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
