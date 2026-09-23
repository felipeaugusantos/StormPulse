import * as Sentry from '@sentry/react'

/** No-op without `VITE_SENTRY_DSN` configured — same "honest opt-in, no
 * silent fake success" pattern as every other optional third-party
 * integration in this project (hCaptcha, VAPID push). A Sentry DSN isn't
 * a secret in the access-control sense (it only lets a client *send*
 * events, same reasoning as the VAPID public key), so it's a plain build
 * arg, not something to hide from the bundle. */
export function initErrorTracking(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    // Error events only — no performance/trace sampling (out of scope
    // here; this is about "an unhandled exception happened", not request
    // tracing).
    tracesSampleRate: 0,
  })
}
