/** Tests for the mobile session/refresh-token flow (hardening Fase 3):
 * login+persistence, an expired access token triggering exactly one
 * transparent refresh+retry, concurrent 401s sharing that one refresh,
 * an invalid refresh clearing the session, and logout. `fetch` and
 * `expo-secure-store` are both faked — no real network/Keychain calls. */

jest.mock('expo-secure-store')

import * as authStorage from '../authStorage'
import { ApiError, api, login, logout, register, satelliteImagePngUrl } from '../api'

// eslint-disable-next-line @typescript-eslint/no-var-requires
const secureStoreMock = require('expo-secure-store') as { __reset: () => void }

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('mobile session (Fase 3)', () => {
  beforeEach(() => {
    secureStoreMock.__reset()
  })

  test('login persists both the access and refresh token', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-1', refresh_token: 'refresh-1' }),
      )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await login('user@example.com', 'senha-super-secreta')

    expect(await authStorage.getAccessToken()).toBe('access-1')
    expect(await authStorage.getRefreshToken()).toBe('refresh-1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/auth/login')
  })

  test('register creates the account, then logs in with the same credentials', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(201, { id: 'user-1', email: 'new@example.com' }))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-1', refresh_token: 'refresh-1' }),
      )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await register('new@example.com', 'supersecret123', 'Nova Usuária')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [registerUrl, registerInit] = fetchMock.mock.calls[0]
    expect(String(registerUrl)).toContain('/auth/register')
    expect(JSON.parse(registerInit.body)).toEqual({
      email: 'new@example.com',
      password: 'supersecret123',
      full_name: 'Nova Usuária',
    })
    expect(String(fetchMock.mock.calls[1][0])).toContain('/auth/login')
    expect(await authStorage.getAccessToken()).toBe('access-1')
  })

  test('an e-mail already in use (409) never attempts the follow-up login', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(409, { detail: 'E-mail já cadastrado' }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(register('taken@example.com', 'supersecret123')).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(await authStorage.getAccessToken()).toBeNull()
  })

  test('an expired access token triggers exactly one refresh, then retries the request', async () => {
    await authStorage.setTokenPair('expired-access', 'still-valid-refresh')

    const fetchMock = jest
      .fn()
      // Original request — access token expired.
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expirado' }))
      // /auth/refresh — succeeds with a new pair.
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'fresh-access', refresh_token: 'fresh-refresh' }),
      )
      // Retried original request — now succeeds.
      .mockResolvedValueOnce(jsonResponse(200, []))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.locations()

    expect(result).toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(String(fetchMock.mock.calls[1][0])).toContain('/auth/refresh')
    // The new pair was persisted for subsequent requests.
    expect(await authStorage.getAccessToken()).toBe('fresh-access')
    expect(await authStorage.getRefreshToken()).toBe('fresh-refresh')
  })

  test('concurrent 401s share a single in-flight refresh call', async () => {
    await authStorage.setTokenPair('expired-access', 'still-valid-refresh')

    let refreshed = false
    const fetchMock = jest.fn().mockImplementation((url: string) => {
      const path = String(url)
      if (path.includes('/auth/refresh')) {
        refreshed = true
        return Promise.resolve(
          jsonResponse(200, { access_token: 'fresh-access', refresh_token: 'fresh-refresh' }),
        )
      }
      // Every non-auth endpoint 401s until the token has been refreshed.
      return Promise.resolve(refreshed ? jsonResponse(200, []) : jsonResponse(401, {}))
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await Promise.all([api.locations(), api.alerts()])

    const refreshCalls = fetchMock.mock.calls.filter((c: unknown[]) =>
      String(c[0]).includes('/auth/refresh'),
    )
    expect(refreshCalls).toHaveLength(1)
  })

  test('an invalid refresh token clears the session and fails as a 401', async () => {
    await authStorage.setTokenPair('expired-access', 'bogus-refresh')

    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, {})) // original request
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'Refresh token inválido' })) // refresh fails
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(api.locations()).rejects.toBeInstanceOf(ApiError)

    expect(await authStorage.getAccessToken()).toBeNull()
    expect(await authStorage.getRefreshToken()).toBeNull()
  })

  test('logout clears both tokens', async () => {
    await authStorage.setTokenPair('access-x', 'refresh-x')

    await logout()

    expect(await authStorage.getAccessToken()).toBeNull()
    expect(await authStorage.getRefreshToken()).toBeNull()
    expect(await authStorage.hasSession()).toBe(false)
  })

  test('login and refresh both identify this client as mobile (ADR-0045)', async () => {
    // Backend hardening Fase 4 defaults REFRESH_COOKIE_ENABLED to true and
    // treats any unrecognized/absent X-Client-Platform as the web/cookie
    // flow — which would silently strip refresh_token from the body and
    // break mobile's SecureStore session. This header is what keeps mobile
    // on the body-token path.
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-1', refresh_token: 'refresh-1' }),
      )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await login('user@example.com', 'senha-super-secreta')

    const [, loginInit] = fetchMock.mock.calls[0]
    expect((loginInit.headers as Record<string, string>)['X-Client-Platform']).toBe('mobile')

    const fetchMock2 = jest
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-2', refresh_token: 'refresh-2' }),
      )
    globalThis.fetch = fetchMock2 as unknown as typeof fetch
    await authStorage.setTokenPair('expired-access', 'refresh-1')
    // Directly exercise the refresh path via a 401'd request.
    fetchMock2.mockReset()
    fetchMock2
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'access-3', refresh_token: 'refresh-3' }),
      )
      .mockResolvedValueOnce(jsonResponse(200, []))

    await api.locations()

    const refreshCall = fetchMock2.mock.calls[1]
    expect(String(refreshCall[0])).toContain('/auth/refresh')
    expect((refreshCall[1].headers as Record<string, string>)['X-Client-Platform']).toBe('mobile')
  })

  test('login is never itself retried through the refresh flow', async () => {
    // A plain wrong-password 401 on /auth/login must surface immediately —
    // never trigger a refresh attempt (there's no session yet to refresh).
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'Credenciais inválidas' }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(login('user@example.com', 'senha-errada')).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('paridade mobile (item 5)', () => {
  beforeEach(async () => {
    secureStoreMock.__reset()
    await authStorage.setTokenPair('access-1', 'refresh-1')
  })

  test('me() fetches the authenticated user profile', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { id: 'user-1', email_verified: false }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const me = await api.me()

    expect(me.email_verified).toBe(false)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/users/me')
  })

  test('deleteAccount() sends the required confirm flag', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce({ ok: true, status: 204 } as Response)
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await api.deleteAccount()

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/users/me')
    expect(init.method).toBe('DELETE')
    expect(JSON.parse(init.body)).toEqual({ confirm: true })
  })

  test('resendVerification() posts to the resend endpoint', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(200, { sent: true }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.resendVerification()

    expect(result).toEqual({ sent: true })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/auth/resend-verification')
  })

  test('storms/lightning/satelliteWatches hit the expected endpoints', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, []))
      .mockResolvedValueOnce(jsonResponse(200, []))
      .mockResolvedValueOnce(jsonResponse(200, []))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await api.storms()
    await api.lightning()
    await api.satelliteWatches()

    expect(String(fetchMock.mock.calls[0][0])).toContain('/storms')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/lightning')
    expect(String(fetchMock.mock.calls[2][0])).toContain('/satellite')
  })

  test('forecastComparison() hits the location-scoped endpoint (Fase 2, ADR-0082)', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(
      jsonResponse(200, { location_id: 'loc-1', min_sample_size: 20, models: [] }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.forecastComparison('loc-1')

    expect(result.models).toEqual([])
    expect(String(fetchMock.mock.calls[0][0])).toContain('/locations/loc-1/forecast-comparison')
  })

  test('vegetationSeries() requests the selected spectral index and history', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(
      jsonResponse(200, { location_id: 'plot-1', index_name: 'evi', current: null, series: [] }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await api.vegetationSeries('plot-1', 'evi', 365)

    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/locations/plot-1/agro/vegetation?index=evi&days=365',
    )
  })

  test('satelliteImage() returns null on a 404 (no cycle run yet)', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(404, { detail: 'not found' }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.satelliteImage()

    expect(result).toBeNull()
  })

  test('satelliteImage() returns the metadata when a frame exists', async () => {
    const meta = { captured_at: '2026-01-01T00:00:00Z', bbox: [-74, -34, -34, 6], band: 'B13' }
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(200, meta))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.satelliteImage()

    expect(result).toEqual(meta)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/public/satellite/image')
  })

  test('satelliteImagePngUrl() builds a public URL with a cache-busting timestamp', () => {
    const url = satelliteImagePngUrl('2026-01-01T00:00:00Z')

    expect(url).toContain('/public/satellite/image.png')
    expect(url).toContain(encodeURIComponent('2026-01-01T00:00:00Z'))
  })
})
