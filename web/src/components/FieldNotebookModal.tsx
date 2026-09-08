import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import { timeAgo } from '../format'
import type {
  FieldInspection,
  FieldOccurrence,
  FieldPhoto,
  FieldTask,
  FieldTimelineEntry,
} from '../types'

interface Props {
  locationId: string
  locationName: string
  latitude: number
  longitude: number
  onClose: () => void
}

type Tab = 'timeline' | 'occurrences' | 'inspections' | 'tasks'

const TAB_LABEL: Record<Tab, string> = {
  timeline: 'Linha do tempo',
  occurrences: 'Ocorrências',
  inspections: 'Inspeções',
  tasks: 'Tarefas',
}

const KIND_ICON: Record<string, string> = {
  occurrence: '⚠️',
  inspection: '🔍',
  task: '✅',
  alert: '🔔',
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'pendente',
  in_progress: 'em andamento',
  done: 'concluída',
  cancelled: 'cancelada',
}

/** Caderno de Campo (Fase 6, ADR-0090) — web é sempre online, então não
 * precisa da fila de sincronização offline que o mobile tem
 * (mobile/src/fieldnotes/); os mesmos endpoints, só sem essa camada. */
export function FieldNotebookModal({ locationId, locationName, latitude, longitude, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('timeline')
  const [timeline, setTimeline] = useState<FieldTimelineEntry[]>([])
  const [occurrences, setOccurrences] = useState<FieldOccurrence[]>([])
  const [inspections, setInspections] = useState<FieldInspection[]>([])
  const [tasks, setTasks] = useState<FieldTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    setError(null)
    Promise.all([
      api.fieldTimeline(locationId),
      api.fieldOccurrences(locationId),
      api.fieldInspections(locationId),
      api.fieldTasks(locationId),
    ])
      .then(([t, o, i, k]) => {
        setTimeline(t)
        setOccurrences(o)
        setInspections(i)
        setTasks(k)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Não foi possível carregar o caderno de campo'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [locationId])

  // Each tab's own list updates itself optimistically on create/update —
  // only the timeline (a merge of all four sources) needs a re-fetch,
  // since it isn't the tab the user is looking at when they act.
  function refreshTimeline() {
    api.fieldTimeline(locationId).then(setTimeline).catch(() => {})
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>📋 Caderno de Campo — {locationName}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading && <p className="panel-hint">carregando…</p>}
        {error && <p className="error">⚠️ {error}</p>}

        {!loading && !error && (
          <>
            <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
              {(['timeline', 'occurrences', 'inspections', 'tasks'] as Tab[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  className={tab === t ? 'btn small' : 'btn ghost small'}
                  onClick={() => setTab(t)}
                >
                  {TAB_LABEL[t]}
                </button>
              ))}
            </div>

            {tab === 'timeline' && <TimelineTab entries={timeline} />}
            {tab === 'occurrences' && (
              <OccurrencesTab
                locationId={locationId}
                latitude={latitude}
                longitude={longitude}
                occurrences={occurrences}
                onCreated={(o) => {
                  setOccurrences((prev) => [o, ...prev])
                  refreshTimeline()
                }}
              />
            )}
            {tab === 'inspections' && (
              <InspectionsTab
                locationId={locationId}
                occurrences={occurrences}
                inspections={inspections}
                onCreated={(i) => {
                  setInspections((prev) => [i, ...prev])
                  refreshTimeline()
                }}
              />
            )}
            {tab === 'tasks' && (
              <TasksTab
                locationId={locationId}
                tasks={tasks}
                onCreated={(t) => {
                  setTasks((prev) => [t, ...prev])
                  refreshTimeline()
                }}
                onUpdated={(t) => {
                  setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
                  refreshTimeline()
                }}
              />
            )}
          </>
        )}

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  )
}

function TimelineTab({ entries }: { entries: FieldTimelineEntry[] }) {
  if (entries.length === 0) return <p className="panel-hint">Nenhum evento registrado ainda.</p>
  return (
    <div className="list">
      {entries.map((e) => (
        <div className="row" key={`${e.kind}-${e.ref_id}`} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <strong>
            {KIND_ICON[e.kind]} {e.title}
          </strong>
          <p className="panel-hint">{e.summary}</p>
          <p className="panel-hint">{timeAgo(e.occurred_at)}</p>
        </div>
      ))}
    </div>
  )
}

function OccurrencesTab({
  locationId,
  latitude,
  longitude,
  occurrences,
  onCreated,
}: {
  locationId: string
  latitude: number
  longitude: number
  occurrences: FieldOccurrence[]
  onCreated: (o: FieldOccurrence) => void
}) {
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit() {
    if (!category.trim() || !description.trim()) return
    setSaving(true)
    try {
      const occurrence = await api.createFieldOccurrence(locationId, {
        category: category.trim(),
        description: description.trim(),
        latitude,
        longitude,
      })
      onCreated(occurrence)
      setCategory('')
      setDescription('')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="location-create-form" style={{ marginBottom: 12 }}>
        <input
          placeholder="Categoria (praga, seca, geada...)"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
        <textarea
          placeholder="O que foi observado?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="location-create-actions">
          <button type="button" className="btn" onClick={submit} disabled={saving}>
            {saving ? 'Salvando…' : '+ Registrar ocorrência'}
          </button>
        </div>
      </div>
      {occurrences.length === 0 ? (
        <p className="panel-hint">Nenhuma ocorrência registrada ainda.</p>
      ) : (
        <div className="list">
          {occurrences.map((o) => (
            <div className="row" key={o.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              <strong>
                {o.category} — {o.status === 'open' ? 'aberta' : 'resolvida'}
              </strong>
              <p className="panel-hint">{o.description}</p>
              <p className="panel-hint">{timeAgo(o.reported_at)}</p>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function InspectionsTab({
  locationId,
  occurrences,
  inspections,
  onCreated,
}: {
  locationId: string
  occurrences: FieldOccurrence[]
  inspections: FieldInspection[]
  onCreated: (i: FieldInspection) => void
}) {
  const [notes, setNotes] = useState('')
  const [occurrenceId, setOccurrenceId] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [photosByInspection, setPhotosByInspection] = useState<Record<string, FieldPhoto[]>>({})
  const [uploadingFor, setUploadingFor] = useState<string | null>(null)

  async function submit() {
    if (!notes.trim()) return
    setSaving(true)
    try {
      const inspection = await api.createFieldInspection(locationId, {
        occurrence_id: occurrenceId || null,
        notes: notes.trim(),
      })
      onCreated(inspection)
      setNotes('')
      setOccurrenceId('')
    } finally {
      setSaving(false)
    }
  }

  async function handleFile(inspectionId: string, file: File | undefined) {
    if (!file) return
    setUploadingFor(inspectionId)
    try {
      const photo = await api.uploadFieldPhoto(inspectionId, file)
      setPhotosByInspection((prev) => ({
        ...prev,
        [inspectionId]: [...(prev[inspectionId] ?? []), photo],
      }))
    } finally {
      setUploadingFor(null)
    }
  }

  return (
    <>
      <div className="location-create-form" style={{ marginBottom: 12 }}>
        {occurrences.length > 0 && (
          <select value={occurrenceId} onChange={(e) => setOccurrenceId(e.target.value)}>
            <option value="">Rotina (sem ocorrência associada)</option>
            {occurrences.map((o) => (
              <option key={o.id} value={o.id}>
                {o.category}
              </option>
            ))}
          </select>
        )}
        <textarea
          placeholder="Notas da inspeção"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className="location-create-actions">
          <button type="button" className="btn" onClick={submit} disabled={saving}>
            {saving ? 'Salvando…' : '+ Nova inspeção'}
          </button>
        </div>
      </div>
      {inspections.length === 0 ? (
        <p className="panel-hint">Nenhuma inspeção registrada ainda.</p>
      ) : (
        <div className="list">
          {inspections.map((i) => (
            <div className="row" key={i.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              <strong>Inspeção</strong>
              <p className="panel-hint">{i.notes}</p>
              <p className="panel-hint">{timeAgo(i.inspected_at)}</p>
              <label className="btn ghost small" style={{ display: 'inline-block', cursor: 'pointer' }}>
                {uploadingFor === i.id ? 'Enviando…' : '📷 Adicionar foto'}
                <input
                  type="file"
                  accept="image/*"
                  style={{ display: 'none' }}
                  disabled={uploadingFor === i.id}
                  onChange={(e) => handleFile(i.id, e.target.files?.[0])}
                />
              </label>
              {(photosByInspection[i.id]?.length ?? 0) > 0 && (
                <p className="panel-hint">{photosByInspection[i.id].length} foto(s) anexada(s)</p>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function TasksTab({
  locationId,
  tasks,
  onCreated,
  onUpdated,
}: {
  locationId: string
  tasks: FieldTask[]
  onCreated: (t: FieldTask) => void
  onUpdated: (t: FieldTask) => void
}) {
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit() {
    if (!title.trim()) return
    setSaving(true)
    try {
      const task = await api.createFieldTask(locationId, { title: title.trim() })
      onCreated(task)
      setTitle('')
    } finally {
      setSaving(false)
    }
  }

  async function markDone(task: FieldTask) {
    const updated = await api.updateFieldTask(task.id, {
      base_version: task.version,
      status: 'done',
    })
    onUpdated(updated)
  }

  return (
    <>
      <div className="location-create-form" style={{ marginBottom: 12 }}>
        <input placeholder="Título da tarefa" value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="location-create-actions">
          <button type="button" className="btn" onClick={submit} disabled={saving}>
            {saving ? 'Salvando…' : '+ Nova tarefa'}
          </button>
        </div>
      </div>
      {tasks.length === 0 ? (
        <p className="panel-hint">Nenhuma tarefa registrada ainda.</p>
      ) : (
        <div className="list">
          {tasks.map((t) => (
            <div className="row" key={t.id} style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              <strong>{t.title}</strong>
              <p className="panel-hint">Status: {STATUS_LABEL[t.status]}</p>
              {t.status !== 'done' && t.status !== 'cancelled' && (
                <button type="button" className="btn ghost small" onClick={() => markDone(t)}>
                  Marcar como concluída
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
