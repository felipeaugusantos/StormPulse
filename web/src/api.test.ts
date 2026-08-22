import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

// Each test gets a fresh module registry so module-level state (the
// refreshInFlight lock) doesn't leak between tests.
async function freshApi() {
  vi.resetModules()
  return await import('./api')
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('login', () => {
  test('stores the refresh token and returns the access token (caller stores it)', async () => {
    // `login()` persists the refresh token itself but returns the access
    // token for the caller to store (Login.tsx calls `setToken` right
    // after) — matches the same split as the mobile client.
    const { login, setToken, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: 'refresh-1' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const access = await login('user@example.com', 'hunter2')
    setToken(access)

    expect(access).toBe('access-1')
    expect(getToken()).toBe('access-1')
    expect(localStorage.getItem('stormpulse.refresh_token')).toBe('refresh-1')
  })

  test('a bad password (401) is surfaced as ApiError, not treated as an expired session', async () => {
    const { login, ApiError } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Credenciais inválidas' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(login('user@example.com', 'wrong')).rejects.toThrow(ApiError)
    // Only the one login call — never retried as if it were a refresh.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('session renewal on 401', () => {
  test('refreshes once and retries the original request', async () => {
    const { api, setToken } = await freshApi()
    localStorage.setItem('stormpulse.access_token', 'expired-access')
    localStorage.setItem('stormpulse.refresh_token', 'refresh-1')
    setToken('expired-access')

    const fetchMock = vi.fn()
    // 1st call: the original request, expired token -> 401.
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'expired' }, 401))
    // 2nd call: POST /auth/refresh -> new pair.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: 'access-2', refresh_token: 'refresh-2' }),
    )
    // 3rd call: retried original request, now succeeds.
    fetchMock.mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.locations()

    expect(result).toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(localStorage.getItem('stormpulse.access_token')).toBe('access-2')
  })

  test('concurrent 401s share a single refresh call', async () => {
    const { api, setToken } = await freshApi()
    setToken('expired-access')
    localStorage.setItem('stormpulse.refresh_token', 'refresh-1')

    let refreshCalls = 0
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/auth/refresh')) {
        refreshCalls += 1
        return Promise.resolve(
          jsonResponse({ access_token: 'access-2', refresh_token: 'refresh-2' }),
        )
      }
      // Every non-refresh call: 401 the first time it sees the old token
      // still attached; subsequent calls (post-refresh retry) succeed.
      return Promise.resolve(jsonResponse([]))
    })
    // First N calls (the two parallel original requests) 401; make that
    // explicit rather than relying on call order.
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({}, 401))
    vi.stubGlobal('fetch', fetchMock)

    await Promise.all([api.locations(), api.alerts()])

    expect(refreshCalls).toBe(1)
  })

  test('an invalid refresh token clears the session instead of looping', async () => {
    const { api, setToken, getToken, ApiError } = await freshApi()
    setToken('expired-access')
    localStorage.setItem('stormpulse.refresh_token', 'garbage')

    const fetchMock = vi.fn()
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 401)) // original request
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'invalid' }, 401)) // refresh fails
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.locations()).rejects.toThrow(ApiError)
    expect(getToken()).toBeNull()
    expect(localStorage.getItem('stormpulse.refresh_token')).toBeNull()
  })

  test('a 401 with no refresh token available is surfaced immediately, no refresh attempted', async () => {
    const { api } = await freshApi()
    // No token at all — e.g. a public/visitor call that unexpectedly 401s.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'nope' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.locations()).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('error states', () => {
  test('a non-JSON error body still produces a usable ApiError', async () => {
    const { api, ApiError } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('<html>502 Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const error = await api.locations().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as InstanceType<typeof ApiError>).status).toBe(502)
  })

  test('a 204 response resolves to undefined, not a JSON parse error', async () => {
    const { api } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.deleteLocation('loc-1')).resolves.toBeUndefined()
  })
})

describe('clearToken (logout)', () => {
  test('removes both tokens from storage', async () => {
    const { clearToken, getToken } = await freshApi()
    localStorage.setItem('stormpulse.access_token', 'a')
    localStorage.setItem('stormpulse.refresh_token', 'r')

    clearToken()

    expect(getToken()).toBeNull()
    expect(localStorage.getItem('stormpulse.refresh_token')).toBeNull()
  })
})
