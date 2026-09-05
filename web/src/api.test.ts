import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

// Each test gets a fresh module registry so module-level state (the access
// token, the refreshInFlight lock) doesn't leak between tests.
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

describe('login (Fase 4 — cookie-based refresh, ADR-0045)', () => {
  test('stores the access token in memory and sends credentials for the cookie', async () => {
    const { login, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await login('user@example.com', 'hunter2')

    expect(getToken()).toBe('access-1')
    const [, init] = fetchMock.mock.calls[0]
    expect(init.credentials).toBe('include')
  })

  test('never writes anything to localStorage', async () => {
    const { login } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await login('user@example.com', 'hunter2')

    expect(localStorage.length).toBe(0)
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

describe('register', () => {
  test('registers the account, then logs in with the same credentials', async () => {
    const { register, getToken } = await freshApi()
    const fetchMock = vi.fn()
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: 'user-1', email: 'new@example.com' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await register('new@example.com', 'supersecret123', 'Nova Usuária')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [registerUrl, registerInit] = fetchMock.mock.calls[0]
    expect(String(registerUrl)).toContain('/auth/register')
    expect(JSON.parse(registerInit.body)).toEqual({
      email: 'new@example.com',
      password: 'supersecret123',
      full_name: 'Nova Usuária',
      storm_module: true,
      agro_module: false,
      accept_terms: false,
      captcha_token: null,
    })
    const [loginUrl] = fetchMock.mock.calls[1]
    expect(String(loginUrl)).toContain('/auth/login')
    expect(getToken()).toBe('access-1')
  })

  test('an e-mail already in use (409) never attempts the follow-up login', async () => {
    const { register, ApiError, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({ detail: 'E-mail já cadastrado' }, 409),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(register('taken@example.com', 'supersecret123')).rejects.toThrow(ApiError)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(getToken()).toBeNull()
  })
})

describe('legacy localStorage migration', () => {
  test('removes old access/refresh token keys on load', async () => {
    localStorage.setItem('stormpulse.access_token', 'old-access')
    localStorage.setItem('stormpulse.refresh_token', 'old-refresh')

    await freshApi()

    expect(localStorage.getItem('stormpulse.access_token')).toBeNull()
    expect(localStorage.getItem('stormpulse.refresh_token')).toBeNull()
  })
})

describe('initSession (app boot)', () => {
  test('redeems a valid refresh cookie for an access token', async () => {
    const { initSession, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const ok = await initSession()

    expect(ok).toBe(true)
    expect(getToken()).toBe('access-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/auth/refresh')
    expect(init.credentials).toBe('include')
  })

  test('returns false (not a thrown error) when there is no valid cookie', async () => {
    const { initSession, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Refresh token ausente' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    const ok = await initSession()

    expect(ok).toBe(false)
    expect(getToken()).toBeNull()
  })
})

describe('session renewal on 401', () => {
  test('refreshes via the cookie and retries the original request once', async () => {
    const { api, login } = await freshApi()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockResolvedValueOnce(jsonResponse({ access_token: 'expired-access', refresh_token: null }))
    await login('user@example.com', 'hunter2')

    // 1st call: the original request, expired token -> 401.
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'expired' }, 401))
    // 2nd call: POST /auth/refresh (cookie-based, no body token) -> new access token.
    fetchMock.mockResolvedValueOnce(jsonResponse({ access_token: 'access-2', refresh_token: null }))
    // 3rd call: retried original request, now succeeds.
    fetchMock.mockResolvedValueOnce(jsonResponse([]))

    const result = await api.locations()

    expect(result).toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(4) // login + 401 + refresh + retry
    const refreshCall = fetchMock.mock.calls[2]
    expect(String(refreshCall[0])).toContain('/auth/refresh')
    expect(refreshCall[1].credentials).toBe('include')
  })

  test('concurrent 401s share a single refresh call', async () => {
    const { api } = await freshApi()
    let refreshCalls = 0
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/auth/refresh')) {
        refreshCalls += 1
        return Promise.resolve(jsonResponse({ access_token: 'access-2', refresh_token: null }))
      }
      return Promise.resolve(jsonResponse([]))
    })
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({}, 401))
    vi.stubGlobal('fetch', fetchMock)

    await Promise.all([api.locations(), api.alerts()])

    expect(refreshCalls).toBe(1)
  })

  test('an invalid/expired cookie clears the session instead of looping', async () => {
    const { api, getToken, ApiError } = await freshApi()
    const fetchMock = vi.fn()
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 401)) // original request
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'invalid' }, 401)) // refresh fails
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.locations()).rejects.toThrow(ApiError)
    expect(getToken()).toBeNull()
  })

  test('a 401 on a fresh session (no prior login) still attempts a refresh, then fails cleanly', async () => {
    const { api } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'nope' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.locations()).rejects.toThrow()
    // original request + one refresh attempt — never an unbounded loop.
    expect(fetchMock).toHaveBeenCalledTimes(2)
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

describe('vegetation intelligence', () => {
  test('requests a typed historical series for the selected index', async () => {
    const { api } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ location_id: 'plot-1', index_name: 'ndmi', current: null, series: [] }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.vegetationSeries('plot-1', 'ndmi', 180)

    expect(String(fetchMock.mock.calls[0][0])).toContain(
      '/locations/plot-1/agro/vegetation?index=ndmi&days=180',
    )
  })
})

describe('logout', () => {
  test('calls the backend and clears the in-memory token', async () => {
    const { login, logout, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)
    await login('user@example.com', 'hunter2')

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await logout()

    expect(getToken()).toBeNull()
    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toContain('/auth/logout')
    expect(init.credentials).toBe('include')
  })

  test('still clears local state even if the network call fails', async () => {
    const { login, logout, getToken } = await freshApi()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ access_token: 'access-1', refresh_token: null }),
    )
    vi.stubGlobal('fetch', fetchMock)
    await login('user@example.com', 'hunter2')

    fetchMock.mockRejectedValueOnce(new Error('network down'))
    await expect(logout()).resolves.toBeUndefined() // never throws

    expect(getToken()).toBeNull()
  })
})
