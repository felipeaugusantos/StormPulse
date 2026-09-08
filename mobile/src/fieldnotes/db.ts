/** Local SQLite-backed sync queue for the Caderno de Campo (Fase 6,
 * ADR-0090) — the first local persistence beyond `expo-secure-store`'s
 * token pair. An inspection/occurrence/task created while offline is
 * written here immediately (so the UI shows it right away) and queued as
 * one pending HTTP operation; `sync.ts` replays the queue in order once
 * connectivity returns.
 *
 * Deliberately NOT a general-purpose offline cache of server data (no
 * local copy of already-synced occurrences/inspections/tasks) — only
 * what's still pending goes here. Read screens hit the API directly and
 * degrade to "couldn't load" when offline, same as the rest of the app;
 * only the *write* path needs to survive being offline.
 */

import * as SQLite from 'expo-sqlite'

export interface PendingOperation {
  id: string
  kind: string
  method: 'POST' | 'PATCH'
  path: string
  body: string
  created_at: string
  last_error: string | null
}

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null

function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = SQLite.openDatabaseAsync('fieldnotes.db').then(async (db) => {
      await db.execAsync(`
        CREATE TABLE IF NOT EXISTS pending_operations (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          method TEXT NOT NULL,
          path TEXT NOT NULL,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_error TEXT
        );
      `)
      return db
    })
  }
  return dbPromise
}

export async function enqueueOperation(op: {
  id: string
  kind: string
  method: 'POST' | 'PATCH'
  path: string
  body: unknown
}): Promise<void> {
  const db = await getDb()
  await db.runAsync(
    'INSERT INTO pending_operations (id, kind, method, path, body, created_at) VALUES (?, ?, ?, ?, ?, ?)',
    op.id,
    op.kind,
    op.method,
    op.path,
    JSON.stringify(op.body),
    new Date().toISOString(),
  )
}

export async function listPendingOperations(): Promise<PendingOperation[]> {
  const db = await getDb()
  return db.getAllAsync<PendingOperation>(
    'SELECT * FROM pending_operations ORDER BY created_at ASC',
  )
}

export async function removeOperation(id: string): Promise<void> {
  const db = await getDb()
  await db.runAsync('DELETE FROM pending_operations WHERE id = ?', id)
}

export async function markOperationError(id: string, error: string): Promise<void> {
  const db = await getDb()
  await db.runAsync('UPDATE pending_operations SET last_error = ? WHERE id = ?', error, id)
}
