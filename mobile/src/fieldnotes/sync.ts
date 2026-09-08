/** Replays the local offline queue (Fase 6, ADR-0090) against the real
 * API through `api.ts`'s own `request()` — same auth/refresh/error
 * handling as every other call in the app, never a second HTTP client.
 *
 * **Conflict handling**: a 409 (stale `base_version`, see backend
 * ADR-0090) is never retried automatically — the operation is dropped
 * from the queue and surfaced to the caller as a conflict, since blindly
 * retrying would just 409 forever and silently discarding it would be
 * exactly the silent-overwrite the backend refuses to do. Any other
 * failure (network down, 5xx) stops the flush entirely so operations
 * later in the queue don't run out of order ahead of one that hasn't
 * synced yet.
 */

import NetInfo, { type NetInfoSubscription } from '@react-native-community/netinfo'
import { ApiError, request } from '../api'
import * as db from './db'

let syncing = false

export interface SyncResult {
  synced: number
  conflicts: string[]
  stoppedEarly: boolean
}

export async function flushPendingOperations(): Promise<SyncResult> {
  if (syncing) return { synced: 0, conflicts: [], stoppedEarly: false }
  syncing = true
  const result: SyncResult = { synced: 0, conflicts: [], stoppedEarly: false }
  try {
    const pending = await db.listPendingOperations()
    for (const op of pending) {
      try {
        await request(op.path, { method: op.method, body: op.body })
        await db.removeOperation(op.id)
        result.synced++
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          await db.removeOperation(op.id)
          result.conflicts.push(op.id)
          continue
        }
        await db.markOperationError(
          op.id,
          err instanceof ApiError ? err.message : 'Falha de rede ao sincronizar',
        )
        result.stoppedEarly = true
        break
      }
    }
  } finally {
    syncing = false
  }
  return result
}

/** Starts flushing automatically whenever connectivity returns — call
 * once (e.g. in App.tsx) and keep the returned unsubscribe function for
 * cleanup. Never flushes on the *first* connected event fired at
 * subscription time with no prior offline period — NetInfo fires an
 * initial state immediately, which would otherwise attempt a flush on
 * every app cold start even with nothing pending (harmless, but noisy).
 */
export function startAutoSync(onResult: (result: SyncResult) => void): NetInfoSubscription {
  let previouslyConnected: boolean | null = null
  return NetInfo.addEventListener((state) => {
    const isConnected = Boolean(state.isConnected && state.isInternetReachable !== false)
    if (isConnected && previouslyConnected === false) {
      flushPendingOperations().then(onResult)
    }
    previouslyConnected = isConnected
  })
}
