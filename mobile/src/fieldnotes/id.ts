/** RFC 4122 v4 UUID generator (Fase 6, ADR-0090) — `Math.random()` is
 * fine here: this is a client-side correlation id used for offline sync
 * idempotency (the backend accepts a caller-supplied `id` and treats a
 * repeat as a no-op replay, see backend/app/fieldnotes/router.py), never
 * a security token. Avoids depending on `crypto.randomUUID()`, which
 * isn't reliably available on every Hermes/React Native version. */
export function generateId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
