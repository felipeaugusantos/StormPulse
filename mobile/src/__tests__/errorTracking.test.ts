jest.mock('@sentry/react-native', () => ({ init: jest.fn() }))

import * as Sentry from '@sentry/react-native'
import { initErrorTracking } from '../errorTracking'

describe('initErrorTracking (Fase 8 follow-up — Sentry)', () => {
  const originalDsn = process.env.EXPO_PUBLIC_SENTRY_DSN

  afterEach(() => {
    process.env.EXPO_PUBLIC_SENTRY_DSN = originalDsn
    jest.mocked(Sentry.init).mockClear()
  })

  test('is a no-op without EXPO_PUBLIC_SENTRY_DSN configured', () => {
    delete process.env.EXPO_PUBLIC_SENTRY_DSN
    initErrorTracking()
    expect(Sentry.init).not.toHaveBeenCalled()
  })

  test('initializes Sentry when a DSN is set', () => {
    process.env.EXPO_PUBLIC_SENTRY_DSN = 'https://examplePublicKey@o0.ingest.sentry.io/0'
    initErrorTracking()
    expect(Sentry.init).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: 'https://examplePublicKey@o0.ingest.sentry.io/0',
        tracesSampleRate: 0,
      }),
    )
  })
})
