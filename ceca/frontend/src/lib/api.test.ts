import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, setApiLocale, setAuthBridge } from './api'

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
    await request('/documents')

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers
    expect(headers.get('Accept-Language')).toBe('en')
  })

  it('convierte {detail:{code,message}} en ApiError con code y message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: { code: 'DOCUMENT_NOT_PDF', message: 'El fichero no es un PDF.' } },
          422,
        ),
      ),
    )

    const error = await request('/documents/').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('DOCUMENT_NOT_PDF')
    expect((error as ApiError).message).toBe('El fichero no es un PDF.')
    expect((error as ApiError).status).toBe(422)
  })

  it('mapea detail.fields del validador DeCA a un objeto por campo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: 'DECA_INVALID',
              message: 'Datos no válidos.',
              fields: [
                { field: 'cargador_nif', code: 'NIF_INVALID', message: 'NIF no válido' },
                { field: 'mercancia_peso', code: 'MIN', message: 'Debe ser mayor que 0' },
              ],
            },
          },
          422,
        ),
      ),
    )

    const error = (await request('/deca/generate', { method: 'POST' }).catch(
      (caught: unknown) => caught,
    )) as ApiError

    expect(error.fields).toEqual({
      cargador_nif: 'NIF no válido',
      mercancia_peso: 'Debe ser mayor que 0',
    })
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

    const result = await request<{ ok: boolean }>('/documents')

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

    await expect(request('/documents')).rejects.toBeInstanceOf(ApiError)

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onAuthFailure).toHaveBeenCalledTimes(1)
  })

  it('no intenta refrescar cuando skipAuth (login y visor publico)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: { code: 'BAD_CREDENTIALS', message: 'x' } }, 401))
    vi.stubGlobal('fetch', fetchMock)

    const refresh = vi.fn()
    setAuthBridge({ getToken: () => null, refresh, onAuthFailure: vi.fn() })

    await expect(request('/auth/login', { method: 'POST', skipAuth: true })).rejects.toBeInstanceOf(
      ApiError,
    )
    expect(refresh).not.toHaveBeenCalled()
  })
})
