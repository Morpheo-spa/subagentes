/**
 * Cliente HTTP de Estampa.
 *
 * Reglas (`.claude/rules/frontend.md`):
 *  - `fetch`, nunca axios.
 *  - El access token vive SOLO en memoria: lo aporta `auth.tsx` por inyeccion.
 *  - Los errores de la API son `{detail: {code, message, fields?}}` y se convierten
 *    en `ApiError`, que expone `.code` (para log) y `.message` (para pintar).
 *  - Un 401 dispara UN solo refresh; si tampoco vale, se cierra sesion.
 */
import type { Locale } from './types'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export const ERROR_CODE_NETWORK = 'NETWORK_ERROR'
export const ERROR_CODE_UNKNOWN = 'UNKNOWN_ERROR'
export const ERROR_CODE_UNAUTHORIZED = 'UNAUTHORIZED'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly fields: Record<string, string> | undefined

  constructor(
    code: string,
    message: string,
    status: number,
    fields?: Record<string, string> | undefined,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.fields = fields
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

/* ---- Estado inyectado ------------------------------------------------ */

export interface AuthBridge {
  /** Access token en memoria, o null si no hay sesion. */
  getToken: () => string | null
  /** Debe pedir un access token nuevo con la cookie httpOnly de refresh. */
  refresh: () => Promise<string | null>
  /** Se llama cuando el refresh tampoco vale. */
  onAuthFailure: () => void
}

let authBridge: AuthBridge | null = null
let currentLocale: Locale = 'es'
let refreshInFlight: Promise<string | null> | null = null

export function setAuthBridge(bridge: AuthBridge | null): void {
  authBridge = bridge
}

export function setApiLocale(locale: Locale): void {
  currentLocale = locale
}

export function getApiLocale(): Locale {
  return currentLocale
}

/** Un unico refresh compartido aunque fallen varias peticiones a la vez. */
function refreshOnce(): Promise<string | null> {
  if (!authBridge) return Promise.resolve(null)
  if (!refreshInFlight) {
    refreshInFlight = authBridge.refresh().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

/* ---- Utilidades ------------------------------------------------------ */

export type QueryValue = string | number | boolean | null | undefined

export function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const base = path.startsWith('http') ? path : `${API_BASE_URL}${path}`
  if (!query) return base
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${base}?${qs}` : base
}

export function buildHeaders(extra?: HeadersInit, token?: string | null): Headers {
  const headers = new Headers(extra)
  headers.set('Accept', 'application/json')
  headers.set('Accept-Language', currentLocale)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

/** Convierte cualquier respuesta no-OK en `ApiError`. */
export async function toApiError(response: Response): Promise<ApiError> {
  let code = ERROR_CODE_UNKNOWN
  let message = response.statusText || `HTTP ${response.status}`
  let fields: Record<string, string> | undefined

  try {
    const payload: unknown = await response.json()
    const detail = (payload as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') {
      message = detail
    } else if (detail && typeof detail === 'object') {
      const d = detail as { code?: unknown; message?: unknown; fields?: unknown }
      if (typeof d.code === 'string') code = d.code
      if (typeof d.message === 'string') message = d.message
      if (Array.isArray(d.fields)) {
        // Formato del validador DeCA: [{field, code, message}]
        fields = {}
        for (const entry of d.fields) {
          const e = entry as { field?: unknown; message?: unknown }
          if (typeof e?.field === 'string' && typeof e?.message === 'string') {
            fields[e.field] = e.message
          }
        }
      } else if (d.fields && typeof d.fields === 'object') {
        fields = {}
        for (const [key, value] of Object.entries(d.fields as Record<string, unknown>)) {
          fields[key] = String(value)
        }
      }
    }
  } catch {
    /* cuerpo no JSON: nos quedamos con el statusText */
  }

  if (code === ERROR_CODE_UNKNOWN && response.status === 401) code = ERROR_CODE_UNAUTHORIZED
  return new ApiError(code, message, response.status, fields)
}

/* ---- Peticiones ------------------------------------------------------ */

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Record<string, QueryValue>
  signal?: AbortSignal
  headers?: HeadersInit
  /** No intentar refresh (login, refresh, logout, visor publico). */
  skipAuth?: boolean
}

async function rawRequest(path: string, options: RequestOptions, token: string | null) {
  const { method = 'GET', body, query, signal, headers } = options
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  const requestHeaders = buildHeaders(headers, options.skipAuth ? null : token)
  if (body !== undefined && !isFormData) requestHeaders.set('Content-Type', 'application/json')

  return fetch(buildUrl(path, query), {
    method,
    headers: requestHeaders,
    credentials: 'include', // cookie httpOnly del refresh token
    signal: signal ?? null,
    body: body === undefined ? null : isFormData ? (body as FormData) : JSON.stringify(body),
  })
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = authBridge?.getToken() ?? null
  let response: Response

  try {
    response = await rawRequest(path, options, token)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(ERROR_CODE_NETWORK, String((error as Error)?.message ?? error), 0)
  }

  // Un solo reintento tras refrescar (nunca dos).
  if (response.status === 401 && !options.skipAuth && authBridge) {
    const fresh = await refreshOnce()
    if (!fresh) {
      authBridge.onAuthFailure()
      throw await toApiError(response)
    }
    try {
      response = await rawRequest(path, options, fresh)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      throw new ApiError(ERROR_CODE_NETWORK, String((error as Error)?.message ?? error), 0)
    }
    if (response.status === 401) {
      authBridge.onAuthFailure()
      throw await toApiError(response)
    }
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('Content-Type') ?? ''
  if (!contentType.includes('application/json')) return (await response.text()) as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

/* ---- Subida con progreso --------------------------------------------- */

export interface UploadOptions<T> {
  path: string
  file: File
  fields?: Record<string, string>
  onProgress?: (percent: number) => void
  signal?: AbortSignal
  parse?: (payload: unknown) => T
}

/**
 * `fetch` todavia no expone progreso de subida en navegadores, asi que esta
 * unica funcion usa XHR. Sigue sin haber axios: mismo parseo de error, mismo
 * token en memoria y el mismo reintento unico tras refrescar.
 */
export function upload<T>(options: UploadOptions<T>): Promise<T> {
  const attempt = (token: string | null, allowRefresh: boolean): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      form.append('file', options.file, options.file.name)
      for (const [key, value] of Object.entries(options.fields ?? {})) form.append(key, value)

      xhr.open('POST', buildUrl(options.path), true)
      xhr.withCredentials = true
      xhr.setRequestHeader('Accept', 'application/json')
      xhr.setRequestHeader('Accept-Language', currentLocale)
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable || !options.onProgress) return
        options.onProgress(Math.min(99, Math.round((event.loaded / event.total) * 100)))
      }

      const abort = () => xhr.abort()
      options.signal?.addEventListener('abort', abort, { once: true })

      const cleanup = () => options.signal?.removeEventListener('abort', abort)

      xhr.onerror = () => {
        cleanup()
        reject(new ApiError(ERROR_CODE_NETWORK, 'network', 0))
      }
      xhr.onabort = () => {
        cleanup()
        reject(new DOMException('aborted', 'AbortError'))
      }
      xhr.onload = () => {
        cleanup()
        let payload: unknown = null
        try {
          payload = xhr.responseText ? JSON.parse(xhr.responseText) : null
        } catch {
          payload = null
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          options.onProgress?.(100)
          resolve(options.parse ? options.parse(payload) : (payload as T))
          return
        }

        if (xhr.status === 401 && allowRefresh && authBridge) {
          refreshOnce()
            .then((fresh) => {
              if (!fresh) {
                authBridge?.onAuthFailure()
                reject(errorFromPayload(payload, xhr.status))
                return
              }
              resolve(attempt(fresh, false))
            })
            .catch(reject)
          return
        }

        reject(errorFromPayload(payload, xhr.status))
      }

      xhr.send(form)
    })

  return attempt(authBridge?.getToken() ?? null, !options.signal?.aborted)
}

/** Mismo contrato de error que `toApiError`, pero sobre un payload ya parseado. */
export function errorFromPayload(payload: unknown, status: number): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object') {
    const d = detail as { code?: unknown; message?: unknown; fields?: unknown }
    const fields =
      d.fields && typeof d.fields === 'object' && !Array.isArray(d.fields)
        ? Object.fromEntries(
            Object.entries(d.fields as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
          )
        : undefined
    return new ApiError(
      typeof d.code === 'string' ? d.code : ERROR_CODE_UNKNOWN,
      typeof d.message === 'string' ? d.message : `HTTP ${status}`,
      status,
      fields,
    )
  }
  return new ApiError(
    status === 401 ? ERROR_CODE_UNAUTHORIZED : ERROR_CODE_UNKNOWN,
    typeof detail === 'string' ? detail : `HTTP ${status}`,
    status,
  )
}
