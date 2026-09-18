import { act, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './auth'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const user = {
  id: 'u1',
  email: 'ana@example.com',
  full_name: 'Ana',
  locale: 'es',
  is_superuser: false,
  default_site_id: null,
}
const site = { id: 's1', name: 'Planta', site_prefix: 'PL', timezone: 'Europe/Madrid', is_active: true }

/** `SessionResponse` tal y como lo devuelve `POST /auth/refresh`: sin refresh_token. */
const session = {
  tokens: { access_token: 'acc-1', token_type: 'bearer', expires_in: 1800 },
  user,
  site,
  permissions: ['documents:read'],
}
const me = { user, site, permissions: ['documents:read'], sites: [], locale: 'es' }

function Probe() {
  const { status, user: current, logout } = useAuth()
  return (
    <div>
      <output data-testid="status">{status}</output>
      <output data-testid="email">{current?.email ?? ''}</output>
      <button type="button" onClick={() => void logout()}>
        salir
      </button>
    </div>
  )
}

function fetchByUrl(handlers: Record<string, () => Response>) {
  return vi.fn((input: unknown) => {
    const url = String(input)
    const handler = Object.entries(handlers).find(([suffix]) => url.endsWith(suffix))?.[1]
    if (!handler) throw new Error(`sin respuesta preparada para ${url}`)
    return Promise.resolve(handler())
  })
}

function callsTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string) {
  return fetchMock.mock.calls.filter((call) => String(call[0]).endsWith(suffix))
}

describe('arranque con sesion persistida en cookie', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('empieza en loading, hace UN solo POST /auth/refresh sin cuerpo y, con 200, hay sesion', async () => {
    const fetchMock = fetchByUrl({
      '/auth/refresh': () => jsonResponse(session),
      '/auth/me': () => jsonResponse(me),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <StrictMode>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </StrictMode>,
    )

    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('email')).toHaveTextContent(user.email)

    // Una sola vez aunque StrictMode monte los efectos dos veces.
    const refreshCalls = callsTo(fetchMock, '/auth/refresh')
    expect(refreshCalls).toHaveLength(1)
    const [url, init] = refreshCalls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/auth/refresh')
    expect(init.method).toBe('POST')
    expect(init.body).toBeNull()
    expect(init.credentials).toBe('include')
    expect((init.headers as Headers).get('Authorization')).toBeNull()
  })

  it('si el refresh responde 401, la sesion queda anonima y se va a login', async () => {
    const fetchMock = fetchByUrl({
      '/auth/refresh': () =>
        jsonResponse({ detail: { code: 'NOT_AUTHENTICATED', message: 'x' } }, 401),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(callsTo(fetchMock, '/auth/refresh')).toHaveLength(1)
    expect(callsTo(fetchMock, '/auth/me')).toHaveLength(0)
  })

  it('logout va con bearer y sin cuerpo: la cookie la revoca y borra el backend', async () => {
    const fetchMock = fetchByUrl({
      '/auth/refresh': () => jsonResponse(session),
      '/auth/me': () => jsonResponse(me),
      '/auth/logout': () => jsonResponse({ ok: true, code: null }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    await act(async () => {
      screen.getByRole('button').click()
    })

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    const [, init] = callsTo(fetchMock, '/auth/logout')[0] as [string, RequestInit]
    expect(init.body).toBeNull()
    expect(init.credentials).toBe('include')
    expect((init.headers as Headers).get('Authorization')).toBe('Bearer acc-1')
  })
})
