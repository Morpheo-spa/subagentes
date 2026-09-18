import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, setApiLocale, setAuthBridge } from './api'
import * as routes from './routes'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('cliente api', () => {
  beforeEach(() => {
    setApiLocale('es')
    setAuthBridge(null)
  })

  afterEach(() => {
    setAuthBridge(null)
    vi.unstubAllGlobals()
  })

  it('manda Accept-Language con el idioma activo', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    setApiLocale('en')
    await request(routes.documentsList())

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers
    expect(headers.get('Accept-Language')).toBe('en')
  })

  it('resuelve las rutas de API bajo /api/v1 y el visor publico en la raiz', async () => {
    // Una respuesta nueva por llamada: un `Response` solo se puede leer una vez.
    const fetchMock = vi.fn<(input: unknown, init?: unknown) => Promise<Response>>(() =>
      Promise.resolve(jsonResponse({ ok: true })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await request(routes.documentRead({ documentId: 'abc' }))
    await request(routes.publicView({ token: 'tok' }), { skipAuth: true })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/documents/abc')
    // `public.router` se monta sin prefijo: `/v/{token}`, no `/api/v1/v/{token}`.
    expect(fetchMock.mock.calls[1][0]).toBe('/v/tok')
  })

  it('usa el verbo que declara la ruta', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request(routes.documentPatchDeca({ documentId: 'abc' }), { body: { deca: {} } })

    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('convierte {detail:{code,message,params}} en ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: 'DOCUMENT_NOT_PDF',
              message: 'El fichero no es un PDF.',
              params: { filename: 'foto.jpg' },
            },
          },
          422,
        ),
      ),
    )

    const error = await request(routes.documentsList()).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('DOCUMENT_NOT_PDF')
    expect((error as ApiError).message).toBe('El fichero no es un PDF.')
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).params).toEqual({ filename: 'foto.jpg' })
  })

  it('refresca el token UNA sola vez ante un 401 y reintenta', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'TOKEN_EXPIRED', message: 'x' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    const refresh = vi.fn().mockResolvedValue('token-nuevo')
    const onAuthFailure = vi.fn()
    setAuthBridge({ getToken: () => 'token-viejo', refresh, onAuthFailure })

    const result = await request<{ ok: boolean }>(routes.documentsList())

    expect(result.ok).toBe(true)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(onAuthFailure).not.toHaveBeenCalled()
    const retryHeaders = (fetchMock.mock.calls[1][1] as RequestInit).headers as Headers
    expect(retryHeaders.get('Authorization')).toBe('Bearer token-nuevo')
  })

  it('no vuelve a refrescar si el reintento sigue dando 401: cierra sesion', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: { code: 'TOKEN_EXPIRED', message: 'x' } }, 401))
    vi.stubGlobal('fetch', fetchMock)

    const refresh = vi.fn().mockResolvedValue('token-nuevo')
    const onAuthFailure = vi.fn()
    setAuthBridge({ getToken: () => 'token-viejo', refresh, onAuthFailure })

    await expect(request(routes.documentsList())).rejects.toBeInstanceOf(ApiError)

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onAuthFailure).toHaveBeenCalledTimes(1)
  })

  it('no intenta refrescar cuando skipAuth (login y visor publico)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: { code: 'INVALID_CREDENTIALS', message: 'x' } }, 401))
    vi.stubGlobal('fetch', fetchMock)

    const refresh = vi.fn()
    setAuthBridge({ getToken: () => null, refresh, onAuthFailure: vi.fn() })

    await expect(
      request(routes.authLogin(), { body: {}, skipAuth: true }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(refresh).not.toHaveBeenCalled()
  })
})
