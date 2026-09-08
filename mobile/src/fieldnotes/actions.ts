/** Offline-first writes for the Caderno de Campo (Fase 6, ADR-0090): try
 * the real API immediately; on any failure (no connectivity, timeout),
 * queue the same request locally and hand back an optimistic record so
 * the screen can show it right away, tagged as pending. `sync.ts` later
 * replays the queue and the optimistic copy is superseded by a real
 * fetch once the screen reloads. */

import { api } from '../api'
import type { FieldOccurrence, FieldTask, Inspection } from '../types'
import * as db from './db'
import { generateId } from './id'

export interface OfflineResult<T> {
  record: T
  queued: boolean
}

export async function createOccurrence(
  locationId: string,
  data: { category: string; description: string; latitude: number; longitude: number },
): Promise<OfflineResult<FieldOccurrence>> {
  const id = generateId()
  const payload = { id, ...data }
  try {
    return { record: await api.createFieldOccurrence(locationId, payload), queued: false }
  } catch {
    await db.enqueueOperation({
      id,
      kind: 'occurrence',
      method: 'POST',
      path: `/locations/${locationId}/field-occurrences`,
      body: payload,
    })
    return {
      queued: true,
      record: {
        id,
        location_id: locationId,
        alert_id: null,
        recommended_action_id: null,
        category: data.category,
        description: data.description,
        latitude: data.latitude,
        longitude: data.longitude,
        status: 'open',
        reported_by: '',
        reported_at: new Date().toISOString(),
        version: 1,
      },
    }
  }
}

export async function createInspection(
  locationId: string,
  data: { occurrence_id?: string | null; notes: string },
): Promise<OfflineResult<Inspection>> {
  const id = generateId()
  const payload = { id, occurrence_id: data.occurrence_id ?? null, notes: data.notes }
  try {
    return { record: await api.createFieldInspection(locationId, payload), queued: false }
  } catch {
    await db.enqueueOperation({
      id,
      kind: 'inspection',
      method: 'POST',
      path: `/locations/${locationId}/field-inspections`,
      body: payload,
    })
    return {
      queued: true,
      record: {
        id,
        location_id: locationId,
        occurrence_id: data.occurrence_id ?? null,
        notes: data.notes,
        latitude: null,
        longitude: null,
        inspected_by: '',
        inspected_at: new Date().toISOString(),
        version: 1,
      },
    }
  }
}

export async function createTask(
  locationId: string,
  data: { title: string; description?: string | null; due_at?: string | null },
): Promise<OfflineResult<FieldTask>> {
  const id = generateId()
  const payload = {
    id,
    title: data.title,
    description: data.description ?? null,
    due_at: data.due_at ?? null,
  }
  try {
    return { record: await api.createFieldTask(locationId, payload), queued: false }
  } catch {
    await db.enqueueOperation({
      id,
      kind: 'task',
      method: 'POST',
      path: `/locations/${locationId}/field-tasks`,
      body: payload,
    })
    return {
      queued: true,
      record: {
        id,
        location_id: locationId,
        occurrence_id: null,
        alert_id: null,
        recommended_action_id: null,
        title: data.title,
        description: data.description ?? null,
        assigned_to: null,
        due_at: data.due_at ?? null,
        status: 'pending',
        completed_by: null,
        completed_at: null,
        version: 1,
      },
    }
  }
}
