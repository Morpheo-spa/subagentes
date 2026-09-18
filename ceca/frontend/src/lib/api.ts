/**
 * Cliente HTTP de Estampa.
 *
 * Reglas (`.claude/rules/frontend.md`):
 *  - `fetch`, nunca axios.
 *  - El access token vive SOLO en memoria: lo aporta `auth.tsx` por inyeccion.
 *  - Los errores de la API son `{detail: {code, message, params?}}` (la unica
 *    forma que permite `app/errors.py:error_detail`) y se convierten en
 *    `ApiError`, que expone `.code` (para log) y `.message` (para pintar).
 *  - Un 401 dispara UN solo refresh; si tampoco vale, se cierra sesion.
 *
 * Las rutas no se escriben aqui ni en los modulos: se piden a `routes.ts`, que
 * es lo unico que el contrato del backend tiene que seguir. Por eso `request`
 * acepta un `ApiRoute` y no una cadena: una ruta a mano no compila.
 */
import type { ApiRoute, RouteBase } from './routes'
import type { Locale } from './types'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
/** El visor publico cuelga de la raiz, no de `/api/v1`. */
export const ROOT_BASE_URL = ''

const BASES: Record<RouteBase, () => string> = {
  api: () => API_BASE_URL,
  root: () => ROOT_BASE_URL,
}

export const ERROR_CODE_NETWORK = 'NETWORK_ERROR'
export const ERROR_CODE_UNKNOWN = 'UNKNOWN_ERROR'
export const ERROR_CODE_UNAUTHORIZED = 'UNAUTHORIZED'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  /** `detail.params` del backend. Para interpolar, nunca para traducir el code. */
  readonly params: Record<string, unknown>

  constructor(code: string, message: string, status: number, params: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.params = params
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

/* ---- Estado inyectado ------------------------------------------------ */

export interface AuthBridge {
  /** Access token en memoria, o null si no hay sesion. */
  getToken: () => string | null
  /** Debe pedir un access token nuevo. */
  refresh: () => Promise<string | null>
  /** Se llama cuando el refresh tampoco vale. */
  onAuthFailure: () => void
}

let authBridge: AuthBridge | null = null
let currentLocale: Locale = 'es'
let refreshInFlight: Promise<string | null> | null = null

export function setAuthBridge(bridge: AuthBridge | null): void {
  authBridge = bridge
  refreshInFlight = null
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

export function buildUrl(route: ApiRoute, query?: Record<string, QueryValue>): string {
  const base = `${BASES[route.base]()}${route.path}`
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
  headers.set('Accept-Language', currentLocale)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

/** Convierte cualquier respuesta no-OK en `ApiError`. */
export async function toApiError(response: Response): Promise<ApiError> {
  let code = ERROR_CODE_UNKNOWN
  let message = response.statusText || `HTTP ${response.status}`
  let params: Record<string, unknown> = {}

  try {
    const payload: unknown = await response.json()
    const detail = (payload as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') {
      message = detail
    } else if (detail && typeof detail === 'object') {
      const d = detail as { code?: unknown; message?: unknown; params?: unknown }
      if (typeof d.code === 'string') code = d.code
      if (typeof d.message === 'string') message = d.message
      if (d.params && typeof d.params === 'object') {
        params = d.params as Record<string, unknown>
      }
    }
  } catch {
    /* cuerpo no JSON: nos quedamos con el statusText */
  }

  if (code === ERROR_CODE_UNKNOWN && response.status === 401) code = ERROR_CODE_UNAUTHORIZED
  return new ApiError(code, message, response.status, params)
}

/* ---- Peticiones ------------------------------------------------------ */

export interface RequestOptions {
  body?: unknown
  query?: Record<string, QueryValue>
  signal?: AbortSignal
  headers?: HeadersInit
  /** No intentar refresh (login, refresh y el visor publico). */
  skipAuth?: boolean
  /** `blob` para binarios servidos por la API (QR, PDF, folio de etiquetas). */
  accept?: 'json' | 'blob'
}

function accepts(options: RequestOptions): string {
  return options.accept === 'blob' ? '*/*' : 'application/json'
}

async function rawRequest(route: ApiRoute, options: RequestOptions, token: string | null) {
  const { body, query, signal, headers } = options
  const requestHeaders = buildHeaders(headers, options.skipAuth ? null : token)
  requestHeaders.set('Accept', accepts(options))
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json')

  return fetch(buildUrl(route, query), {
    method: route.method,
    headers: requestHeaders,
    signal: signal ?? null,
    body: body === undefined ? null : JSON.stringify(body),
  })
}

async function send(route: ApiRoute, options: RequestOptions): Promise<Response> {
  const token = authBridge?.getToken() ?? null
  let response: Response

  try {
    response = await rawRequest(route, options, token)
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
      response = await rawRequest(route, options, fresh)
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
  return response
}

/** Llama a una ruta del registro. El verbo lo pone la ruta, no quien la usa. */
export async function request<T>(route: ApiRoute, options: RequestOptions = {}): Promise<T> {
  const response = await send(route, options)
  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('Content-Type') ?? ''
  if (!contentType.includes('application/json')) return (await response.text()) as T
  return (await response.json()) as T
}

/**
 * Binario servido por la API. Hace falta porque el QR y el PDF van detras del
 * bearer: un `<img src>` no lleva cabeceras, asi que se descarga y se pinta
 * desde un object URL.
 */
export async function requestBlob(route: ApiRoute, options: RequestOptions = {}): Promise<Blob> {
  const response = await send(route, { ...options, accept: 'blob' })
  return response.blob()
}

/* ---- Subida con progreso --------------------------------------------- */

export interface UploadOptions {
  route: ApiRoute
  /** `POST /documents/` acepta varios ficheros en el campo `files`. */
  files: File[]
  /** Metadatos DeCA comunes a la tanda: viajan como JSON en un campo `deca`. */
  deca?: Record<string, unknown>
  retentionPolicyId?: string | null
  onProgress?: (percent: number) => void
  signal?: AbortSignal
}

/**
 * `fetch` todavia no expone progreso de subida en navegadores, asi que esta
 * unica funcion usa XHR. Sigue sin haber axios: mismo parseo de error, mismo
 * token en memoria y el mismo reintento unico tras refrescar.
 */
export function upload<T>(options: UploadOptions): Promise<T> {
  const attempt = (token: string | null, allowRefresh: boolean): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      for (const file of options.files) form.append('files', file, file.name)
      if (options.deca) form.append('deca', JSON.stringify(options.deca))
      if (options.retentionPolicyId) form.append('retention_policy_id', options.retentionPolicyId)

      xhr.open(options.route.method, buildUrl(options.route), true)
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
          resolve(payload as T)
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
    const d = detail as { code?: unknown; message?: unknown; params?: unknown }
    return new ApiError(
      typeof d.code === 'string' ? d.code : ERROR_CODE_UNKNOWN,
      typeof d.message === 'string' ? d.message : `HTTP ${status}`,
      status,
      d.params && typeof d.params === 'object' ? (d.params as Record<string, unknown>) : {},
    )
  }
  return new ApiError(
    status === 401 ? ERROR_CODE_UNAUTHORIZED : ERROR_CODE_UNKNOWN,
    typeof detail === 'string' ? detail : `HTTP ${status}`,
    status,
  )
}
