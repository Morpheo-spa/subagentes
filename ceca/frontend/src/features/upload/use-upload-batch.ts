/**
 * Tanda de subida (upload.md).
 * En cola -> Subiendo % -> Procesando -> Listo | Error.
 * Nada de un toast por fichero: el recuento va por `aria-live` en la pagina.
 *
 * `POST /documents/` admite varios ficheros de golpe, pero aqui va uno por
 * peticion: es la unica forma de dar progreso por fila y de que un fichero que
 * falla no arrastre a los demas (el backend ya devuelve un resultado por
 * fichero, `UploadItemResult`; con uno solo, es una lista de uno).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, request, upload } from '@/lib/api'
import * as routes from '@/lib/routes'
import {
  WARNING_DUPLICATE,
  WARNING_METADATA_VISIBLE,
  WARNING_SCAN,
  type DocumentSummary,
  type UploadResponse,
  type UploadWarning,
} from '@/lib/types'

export type BatchItemStatus = 'queued' | 'uploading' | 'processing' | 'ready' | 'error' | 'rejected'

export interface BatchItem {
  id: string
  file: File
  name: string
  size: number
  status: BatchItemStatus
  progress: number
  errorCode: string | null
  errorMessage: string | null
  document: DocumentSummary | null
  /** Avisos del backend: duplicado, escaneo, metadatos visibles. El fichero se archiva igual. */
  warnings: UploadWarning[]
}

/**
 * Tope legal del fichero DeCA (docs/DECA.md §4: 5 MB por fichero).
 *
 * No hay endpoint que lo sirva: `GET /documents/limits` no existe en el
 * backend. Es una constante de la norma, no una preferencia de tenant, asi que
 * vive aqui; el backend vuelve a comprobarlo y la cuota del plan la aplica el.
 */
export const MAX_UPLOAD_BYTES = 5_000_000

const MAX_CONCURRENT = 3
const POLL_INTERVAL_MS = 1500
const POLL_MAX_TRIES = 60

export const REJECT_NOT_PDF = 'UPLOAD_NOT_PDF'
export const REJECT_TOO_LARGE = 'UPLOAD_TOO_LARGE'

let sequence = 0
function nextId() {
  sequence += 1
  return `batch-${sequence}-${Date.now()}`
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export function hasWarning(item: BatchItem, code: string): boolean {
  return item.warnings.some((warning) => warning.code === code)
}

export function isDuplicate(item: BatchItem): boolean {
  return hasWarning(item, WARNING_DUPLICATE)
}

/**
 * Metadatos del PDF (autor, titulo...) que quedaran a la vista de quien escanee
 * el QR. Informativo: no bloquea nada, y pesa menos que duplicado o escaneo.
 */
export function metadataWarning(item: BatchItem): UploadWarning | null {
  return item.warnings.find((warning) => warning.code === WARNING_METADATA_VISIBLE) ?? null
}

/** `params.fields` del aviso, como lista de nombres. Cualquier otra forma, vacia. */
export function visibleMetadataFields(warning: UploadWarning | null): string[] {
  const fields = warning?.params.fields
  return Array.isArray(fields) ? fields.filter((f): f is string => typeof f === 'string') : []
}

/**
 * Un escaneo se archiva, pero NO es un DeCA valido: no se le ofrece etiqueta
 * (docs/DECA.md §1 y MASTER §10 bis).
 */
export function isPrintable(item: BatchItem): boolean {
  return item.status === 'ready' && Boolean(item.document?.is_valid_deca)
}

export function isScan(item: BatchItem): boolean {
  return (
    hasWarning(item, WARNING_SCAN) ||
    item.document?.compliance_status === 'not_a_deca' ||
    item.document?.origin === 'uploaded_scanned'
  )
}

export function useUploadBatch() {
  const [items, setItems] = useState<BatchItem[]>([])
  const startedRef = useRef<Set<string>>(new Set())
  const abortersRef = useRef<Map<string, AbortController>>(new Map())

  const patch = useCallback((id: string, changes: Partial<BatchItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)))
  }, [])

  const addFiles = useCallback((files: File[]) => {
    const created = files.map<BatchItem>((file) => {
      const base: BatchItem = {
        id: nextId(),
        file,
        name: file.name,
        size: file.size,
        status: 'queued',
        progress: 0,
        errorCode: null,
        errorMessage: null,
        document: null,
        warnings: [],
      }
      // Validacion en cliente ANTES de subir (upload.md).
      if (!isPdf(file)) return { ...base, status: 'rejected', errorCode: REJECT_NOT_PDF }
      if (file.size > MAX_UPLOAD_BYTES) {
        return { ...base, status: 'rejected', errorCode: REJECT_TOO_LARGE }
      }
      return base
    })
    setItems((current) => [...current, ...created])
    return created
  }, [])

  const pollUntilSettled = useCallback(
    async (id: string, documentId: string) => {
      for (let attempt = 0; attempt < POLL_MAX_TRIES; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS))
        try {
          const fresh = await request<DocumentSummary>(routes.documentRead({ documentId }))
          if (fresh.status === 'ready') {
            patch(id, { status: 'ready', progress: 100, document: fresh })
            return
          }
          if (fresh.status === 'failed' || fresh.status === 'withdrawn') {
            patch(id, {
              status: 'error',
              errorCode: 'DOCUMENT_PROCESSING_FAILED',
              document: fresh,
            })
            return
          }
        } catch (error) {
          patch(id, {
            status: 'error',
            errorCode: error instanceof ApiError ? error.code : 'UNKNOWN_ERROR',
            errorMessage: error instanceof ApiError ? error.message : null,
          })
          return
        }
      }
      patch(id, { status: 'error', errorCode: 'DOCUMENT_PROCESSING_TIMEOUT' })
    },
    [patch],
  )

  const runItem = useCallback(
    async (item: BatchItem) => {
      const controller = new AbortController()
      abortersRef.current.set(item.id, controller)
      patch(item.id, {
        status: 'uploading',
        progress: 0,
        errorCode: null,
        errorMessage: null,
        warnings: [],
      })

      try {
        const result = await upload<UploadResponse>({
          route: routes.documentsUpload(),
          files: [item.file],
          signal: controller.signal,
          onProgress: (progress) => patch(item.id, { progress }),
        })

        const entry = result.items[0]
        if (!entry) {
          patch(item.id, { status: 'error', errorCode: 'UPLOAD_EMPTY_RESPONSE' })
          return
        }

        // Un fichero rechazado es una fila con error, no una tanda perdida.
        if (!entry.accepted || !entry.document) {
          patch(item.id, {
            status: 'error',
            errorCode: entry.error?.code ?? 'UNKNOWN_ERROR',
            errorMessage: entry.error?.message ?? null,
            warnings: entry.warnings,
          })
          return
        }

        const document = entry.document
        patch(item.id, { warnings: entry.warnings, document, progress: 100 })

        if (document.status === 'ready') {
          patch(item.id, { status: 'ready' })
          return
        }
        patch(item.id, { status: 'processing' })
        await pollUntilSettled(item.id, document.id)
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          patch(item.id, { status: 'queued', progress: 0 })
          return
        }
        patch(item.id, {
          status: 'error',
          errorCode: error instanceof ApiError ? error.code : 'UNKNOWN_ERROR',
          errorMessage: error instanceof ApiError ? error.message : null,
        })
      } finally {
        abortersRef.current.delete(item.id)
      }
    },
    [patch, pollUntilSettled],
  )

  // Arranca hasta MAX_CONCURRENT subidas; no relanza lo ya empezado.
  useEffect(() => {
    const active = items.filter(
      (item) => item.status === 'uploading' || item.status === 'processing',
    ).length
    const pending = items.filter(
      (item) => item.status === 'queued' && !startedRef.current.has(item.id),
    )
    for (const item of pending.slice(0, Math.max(0, MAX_CONCURRENT - active))) {
      startedRef.current.add(item.id)
      void runItem(item)
    }
  }, [items, runItem])

  const retry = useCallback(
    (id: string) => {
      const item = items.find((entry) => entry.id === id)
      if (!item) return
      startedRef.current.add(id)
      void runItem(item)
    },
    [items, runItem],
  )

  const remove = useCallback((id: string) => {
    abortersRef.current.get(id)?.abort()
    abortersRef.current.delete(id)
    startedRef.current.delete(id)
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const clear = useCallback(() => {
    for (const controller of abortersRef.current.values()) controller.abort()
    abortersRef.current.clear()
    startedRef.current.clear()
    setItems([])
  }, [])

  const readyItems = items.filter((item) => item.status === 'ready' && item.document)
  const printableItems = items.filter(isPrintable)
  const inFlight = items.some(
    (item) => item.status === 'uploading' || item.status === 'processing',
  )

  return {
    items,
    addFiles,
    retry,
    remove,
    clear,
    readyItems,
    printableItems,
    inFlight,
    counts: {
      total: items.length,
      ready: readyItems.length,
      errors: items.filter((item) => item.status === 'error' || item.status === 'rejected').length,
    },
    maxBytes: MAX_UPLOAD_BYTES,
  }
}
