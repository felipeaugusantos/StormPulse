import * as Sentry from '@sentry/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { initErrorTracking } from './errorTracking'

vi.mock('@sentry/react', () => ({ init: vi.fn() }))

describe('initErrorTracking', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.mocked(Sentry.init).mockClear()
  })

  test('is a no-op without VITE_SENTRY_DSN configured', () => {
    vi.stubEnv('VITE_SENTRY_DSN', '')
    initErrorTracking()
    expect(Sentry.init).not.toHaveBeenCalled()
  })

  test('initializes Sentry when a DSN is set', () => {
    vi.stubEnv('VITE_SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')
    initErrorTracking()
    expect(Sentry.init).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'https://examplePublicKey@o0.ingest.sentry.io/0',
        tracesSampleRate: 0,
      }),
    )
  })
})
