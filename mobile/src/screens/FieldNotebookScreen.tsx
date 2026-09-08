import { useCallback, useEffect, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import * as ImageManipulator from 'expo-image-manipulator'
import * as ImagePicker from 'expo-image-picker'
import { ApiError, api } from '../api'
import { createInspection, createOccurrence, createTask } from '../fieldnotes/actions'
import { flushPendingOperations } from '../fieldnotes/sync'
import { timeAgo } from '../format'
import type {
  FieldOccurrence,
  FieldPhoto,
  FieldTask,
  FieldTimelineEntry,
  Inspection,
  LocationItem,
} from '../types'
import { colors } from '../theme'

interface Props {
  location: LocationItem
  onClose: () => void
}

type Tab = 'timeline' | 'occurrences' | 'inspections' | 'tasks'

/** Caderno de Campo (Fase 6, ADR-0090) — occurrences/inspections/tasks
 * for one talhão. Creates go through `fieldnotes/actions.ts` (offline-
 * first: tries the API, falls back to a local queue on failure) — reads
 * always hit the API directly and show an honest "sem conexão" instead
 * of pretending a cached list is current. */
export function FieldNotebookScreen({ location, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('timeline')
  const [timeline, setTimeline] = useState<FieldTimelineEntry[]>([])
  const [occurrences, setOccurrences] = useState<FieldOccurrence[]>([])
  const [inspections, setInspections] = useState<Inspection[]>([])
  const [tasks, setTasks] = useState<FieldTask[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingNotice, setPendingNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [t, o, i, k] = await Promise.all([
        api.fieldTimeline(location.id),
        api.fieldOccurrences(location.id),
        api.fieldInspections(location.id),
        api.fieldTasks(location.id),
      ])
      setTimeline(t)
      setOccurrences(o)
      setInspections(i)
      setTasks(k)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sem conexão — mostrando o que já foi carregado.')
    } finally {
      setLoading(false)
    }
  }, [location.id])

  useEffect(() => {
    load()
  }, [load])

  // Each tab's own list updates itself optimistically on create/update —
  // only the timeline (a merge of all four sources) needs a re-fetch,
  // since it isn't the tab the user is looking at when they act.
  const refreshTimeline = useCallback(() => {
    api.fieldTimeline(location.id).then(setTimeline).catch(() => {})
  }, [location.id])

  async function handleSyncNow() {
    const result = await flushPendingOperations()
    if (result.synced > 0 || result.conflicts.length > 0) {
      setPendingNotice(
        `${result.synced} sincronizado(s)` +
          (result.conflicts.length > 0 ? `, ${result.conflicts.length} em conflito` : ''),
      )
      await load()
    } else {
      setPendingNotice('Nada pendente para sincronizar.')
    }
  }

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <TouchableOpacity onPress={onClose}>
          <Text style={styles.back}>← Voltar</Text>
        </TouchableOpacity>
        <Text style={styles.title}>📋 Caderno — {location.name}</Text>
        <TouchableOpacity onPress={handleSyncNow}>
          <Text style={styles.syncButton}>🔄 Sincronizar</Text>
        </TouchableOpacity>
      </View>

      {pendingNotice && <Text style={styles.notice}>{pendingNotice}</Text>}
      {error && <Text style={styles.error}>⚠️ {error}</Text>}

      <View style={styles.tabs}>
        {(['timeline', 'occurrences', 'inspections', 'tasks'] as Tab[]).map((t) => (
          <TouchableOpacity key={t} onPress={() => setTab(t)} style={styles.tabButton}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {TAB_LABEL[t]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading && <ActivityIndicator color={colors.accent} style={{ marginTop: 16 }} />}

      <ScrollView style={styles.content} contentContainerStyle={{ paddingBottom: 32 }}>
        {tab === 'timeline' && <TimelineTab entries={timeline} />}
        {tab === 'occurrences' && (
          <OccurrencesTab
            location={location}
            occurrences={occurrences}
            onCreated={(o, queued) => {
              setOccurrences((prev) => [o, ...prev])
              refreshTimeline()
              if (queued) setPendingNotice('Salvo offline — será sincronizado ao reconectar.')
            }}
          />
        )}
        {tab === 'inspections' && (
          <InspectionsTab
            location={location}
            occurrences={occurrences}
            inspections={inspections}
            onCreated={(i, queued) => {
              setInspections((prev) => [i, ...prev])
              refreshTimeline()
              if (queued) setPendingNotice('Salvo offline — será sincronizado ao reconectar.')
            }}
          />
        )}
        {tab === 'tasks' && (
          <TasksTab
            location={location}
            tasks={tasks}
            onCreated={(t, queued) => {
              setTasks((prev) => [t, ...prev])
              refreshTimeline()
              if (queued) setPendingNotice('Salvo offline — será sincronizado ao reconectar.')
            }}
            onUpdated={(t) => {
              setTasks((prev) => prev.map((x) => (x.id === t.id ? t : x)))
              refreshTimeline()
            }}
          />
        )}
      </ScrollView>
    </View>
  )
}

const TAB_LABEL: Record<Tab, string> = {
  timeline: 'Linha do tempo',
  occurrences: 'Ocorrências',
  inspections: 'Inspeções',
  tasks: 'Tarefas',
}

function TimelineTab({ entries }: { entries: FieldTimelineEntry[] }) {
  if (entries.length === 0) return <Text style={styles.empty}>Nenhum evento registrado ainda.</Text>
  return (
    <>
      {entries.map((e) => (
        <View key={`${e.kind}-${e.ref_id}`} style={styles.card}>
          <Text style={styles.cardTitle}>
            {KIND_ICON[e.kind]} {e.title}
          </Text>
          <Text style={styles.cardBody}>{e.summary}</Text>
          <Text style={styles.cardMeta}>{timeAgo(e.occurred_at)}</Text>
        </View>
      ))}
    </>
  )
}

const KIND_ICON: Record<string, string> = {
  occurrence: '⚠️',
  inspection: '🔍',
  task: '✅',
  alert: '🔔',
}

function OccurrencesTab({
  location,
  occurrences,
  onCreated,
}: {
  location: LocationItem
  occurrences: FieldOccurrence[]
  onCreated: (o: FieldOccurrence, queued: boolean) => void
}) {
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit() {
    if (!category.trim() || !description.trim()) return
    setSaving(true)
    try {
      const { record, queued } = await createOccurrence(location.id, {
        category: category.trim(),
        description: description.trim(),
        latitude: location.latitude,
        longitude: location.longitude,
      })
      onCreated(record, queued)
      setCategory('')
      setDescription('')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <View style={styles.form}>
        <TextInput
          style={styles.input}
          placeholder="Categoria (praga, seca, geada...)"
          placeholderTextColor={colors.inkMute}
          value={category}
          onChangeText={setCategory}
        />
        <TextInput
          style={styles.input}
          placeholder="O que foi observado?"
          placeholderTextColor={colors.inkMute}
          value={description}
          onChangeText={setDescription}
          multiline
        />
        <TouchableOpacity style={styles.primaryButton} onPress={submit} disabled={saving}>
          <Text style={styles.primaryButtonText}>
            {saving ? 'Salvando…' : '+ Registrar ocorrência'}
          </Text>
        </TouchableOpacity>
      </View>
      {occurrences.length === 0 ? (
        <Text style={styles.empty}>Nenhuma ocorrência registrada ainda.</Text>
      ) : (
        occurrences.map((o) => (
          <View key={o.id} style={styles.card}>
            <Text style={styles.cardTitle}>
              {o.category} — {o.status === 'open' ? 'aberta' : 'resolvida'}
            </Text>
            <Text style={styles.cardBody}>{o.description}</Text>
            <Text style={styles.cardMeta}>{timeAgo(o.reported_at)}</Text>
          </View>
        ))
      )}
    </>
  )
}

function InspectionsTab({
  location,
  occurrences,
  inspections,
  onCreated,
}: {
  location: LocationItem
  occurrences: FieldOccurrence[]
  inspections: Inspection[]
  onCreated: (i: Inspection, queued: boolean) => void
}) {
  const [notes, setNotes] = useState('')
  const [occurrenceId, setOccurrenceId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [photosByInspection, setPhotosByInspection] = useState<Record<string, FieldPhoto[]>>({})
  const [uploadingFor, setUploadingFor] = useState<string | null>(null)

  async function submit() {
    if (!notes.trim()) return
    setSaving(true)
    try {
      const { record, queued } = await createInspection(location.id, {
        occurrence_id: occurrenceId,
        notes: notes.trim(),
      })
      onCreated(record, queued)
      setNotes('')
      setOccurrenceId(null)
    } finally {
      setSaving(false)
    }
  }

  async function addPhoto(inspectionId: string) {
    const permission = await ImagePicker.requestCameraPermissionsAsync()
    if (!permission.granted) {
      Alert.alert('Permissão necessária', 'Autorize o acesso à câmera para anexar uma foto.')
      return
    }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.8 })
    if (result.canceled || result.assets.length === 0) return

    setUploadingFor(inspectionId)
    try {
      // Compress before upload — the backend rejects an uncompressed
      // photo above 15 MB (ADR-0090), and mobile data is expensive.
      const compressed = await ImageManipulator.manipulateAsync(
        result.assets[0].uri,
        [{ resize: { width: 1600 } }],
        { compress: 0.6, format: ImageManipulator.SaveFormat.JPEG },
      )
      const photo = await api.uploadFieldPhoto(inspectionId, {
        uri: compressed.uri,
        name: 'inspecao.jpg',
        type: 'image/jpeg',
      })
      setPhotosByInspection((prev) => ({
        ...prev,
        [inspectionId]: [...(prev[inspectionId] ?? []), photo],
      }))
    } catch (err) {
      Alert.alert(
        'Falha ao enviar foto',
        err instanceof ApiError
          ? err.message
          : 'Sem conexão — tente novamente quando estiver online (fotos não entram na fila offline).',
      )
    } finally {
      setUploadingFor(null)
    }
  }

  return (
    <>
      <View style={styles.form}>
        {occurrences.length > 0 && (
          <View style={styles.chipRow}>
            <TouchableOpacity
              style={[styles.chip, occurrenceId === null && styles.chipActive]}
              onPress={() => setOccurrenceId(null)}
            >
              <Text style={styles.chipText}>Rotina</Text>
            </TouchableOpacity>
            {occurrences.map((o) => (
              <TouchableOpacity
                key={o.id}
                style={[styles.chip, occurrenceId === o.id && styles.chipActive]}
                onPress={() => setOccurrenceId(o.id)}
              >
                <Text style={styles.chipText}>{o.category}</Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
        <TextInput
          style={styles.input}
          placeholder="Notas da inspeção"
          placeholderTextColor={colors.inkMute}
          value={notes}
          onChangeText={setNotes}
          multiline
        />
        <TouchableOpacity style={styles.primaryButton} onPress={submit} disabled={saving}>
          <Text style={styles.primaryButtonText}>{saving ? 'Salvando…' : '+ Nova inspeção'}</Text>
        </TouchableOpacity>
      </View>
      {inspections.length === 0 ? (
        <Text style={styles.empty}>Nenhuma inspeção registrada ainda.</Text>
      ) : (
        inspections.map((i) => (
          <View key={i.id} style={styles.card}>
            <Text style={styles.cardTitle}>Inspeção</Text>
            <Text style={styles.cardBody}>{i.notes}</Text>
            <Text style={styles.cardMeta}>{timeAgo(i.inspected_at)}</Text>
            <TouchableOpacity
              onPress={() => addPhoto(i.id)}
              disabled={uploadingFor === i.id}
              style={styles.photoButton}
            >
              <Text style={styles.photoButtonText}>
                {uploadingFor === i.id ? 'Enviando…' : '📷 Adicionar foto'}
              </Text>
            </TouchableOpacity>
            {(photosByInspection[i.id]?.length ?? 0) > 0 && (
              <Text style={styles.cardMeta}>
                {photosByInspection[i.id].length} foto(s) anexada(s)
              </Text>
            )}
          </View>
        ))
      )}
    </>
  )
}

function TasksTab({
  location,
  tasks,
  onCreated,
  onUpdated,
}: {
  location: LocationItem
  tasks: FieldTask[]
  onCreated: (t: FieldTask, queued: boolean) => void
  onUpdated: (t: FieldTask) => void
}) {
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit() {
    if (!title.trim()) return
    setSaving(true)
    try {
      const { record, queued } = await createTask(location.id, { title: title.trim() })
      onCreated(record, queued)
      setTitle('')
    } finally {
      setSaving(false)
    }
  }

  async function markDone(task: FieldTask) {
    try {
      const updated = await api.updateFieldTask(task.id, {
        base_version: task.version,
        status: 'done',
      })
      onUpdated(updated)
    } catch (err) {
      Alert.alert(
        'Não foi possível concluir a tarefa',
        err instanceof ApiError ? err.message : 'Sem conexão.',
      )
    }
  }

  return (
    <>
      <View style={styles.form}>
        <TextInput
          style={styles.input}
          placeholder="Título da tarefa"
          placeholderTextColor={colors.inkMute}
          value={title}
          onChangeText={setTitle}
        />
        <TouchableOpacity style={styles.primaryButton} onPress={submit} disabled={saving}>
          <Text style={styles.primaryButtonText}>{saving ? 'Salvando…' : '+ Nova tarefa'}</Text>
        </TouchableOpacity>
      </View>
      {tasks.length === 0 ? (
        <Text style={styles.empty}>Nenhuma tarefa registrada ainda.</Text>
      ) : (
        tasks.map((t) => (
          <View key={t.id} style={styles.card}>
            <Text style={styles.cardTitle}>{t.title}</Text>
            <Text style={styles.cardMeta}>Status: {STATUS_LABEL[t.status]}</Text>
            {t.status !== 'done' && t.status !== 'cancelled' && (
              <TouchableOpacity onPress={() => markDone(t)} style={styles.photoButton}>
                <Text style={styles.photoButtonText}>Marcar como concluída</Text>
              </TouchableOpacity>
            )}
          </View>
        ))
      )}
    </>
  )
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'pendente',
  in_progress: 'em andamento',
  done: 'concluída',
  cancelled: 'cancelada',
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground, paddingTop: 48 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    marginBottom: 8,
  },
  back: { color: colors.accent, fontSize: 14 },
  title: { color: colors.ink, fontSize: 16, fontWeight: '700', flexShrink: 1 },
  syncButton: { color: colors.accent, fontSize: 12 },
  notice: { color: colors.green, paddingHorizontal: 16, marginBottom: 4 },
  error: { color: colors.red, paddingHorizontal: 16, marginBottom: 4 },
  tabs: { flexDirection: 'row', paddingHorizontal: 16, marginBottom: 8, flexWrap: 'wrap' },
  tabButton: { marginRight: 16, paddingVertical: 6 },
  tabText: { color: colors.inkMute, fontSize: 13 },
  tabTextActive: { color: colors.accent, fontWeight: '700' },
  content: { flex: 1, paddingHorizontal: 16 },
  form: { marginBottom: 16 },
  input: {
    backgroundColor: colors.panel2,
    color: colors.ink,
    borderRadius: 8,
    padding: 10,
    marginBottom: 8,
  },
  primaryButton: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    padding: 10,
    alignItems: 'center',
  },
  primaryButtonText: { color: colors.ground, fontWeight: '700' },
  card: {
    backgroundColor: colors.panel,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.line,
  },
  cardTitle: { color: colors.ink, fontWeight: '700', marginBottom: 4 },
  cardBody: { color: colors.ink, marginBottom: 4 },
  cardMeta: { color: colors.inkMute, fontSize: 12 },
  empty: { color: colors.inkMute, marginBottom: 16 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8 },
  chip: {
    backgroundColor: colors.panel2,
    borderRadius: 16,
    paddingVertical: 4,
    paddingHorizontal: 10,
    marginRight: 6,
    marginBottom: 6,
  },
  chipActive: { backgroundColor: colors.accent },
  chipText: { color: colors.ink, fontSize: 12 },
  photoButton: { marginTop: 6 },
  photoButtonText: { color: colors.accent, fontSize: 12 },
})
