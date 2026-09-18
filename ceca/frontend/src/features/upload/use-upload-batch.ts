/**
 * Tanda de subida (upload.md).
 * En cola -> Subiendo % -> Procesando -> Listo | Error.
 * Nada de un toast por fichero: el recuento va por `aria-live` en la pagina.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, upload } from '@/lib/api'
import type { DocumentSummary } from '@/lib/types'

export type BatchItemStatus =
  | 'queued'
  | 'uploading'
  | 'processing'
  | 'ready'
  | 'error'
  | 'duplicate'
  | 'rejected'

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
  duplicateOf: DocumentSummary | null
}

export interface UploadResponse {
  document: DocumentSummary | null
  duplicate_of: DocumentSummary | null
}

export interface ClientLimits {
  max_upload_mb: number
  accepted_content_types: string[]
}

/** Tope legal del fichero DeCA si la API aun no ha respondido (docs/DECA.md §4). */
export const FALLBACK_MAX_UPLOAD_MB = 5
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

export function useUploadBatch(limits: ClientLimits | undefined) {
  const [items, setItems] = useState<BatchItem[]>([])
  const startedRef = useRef<Set<string>>(new Set())
  const abortersRef = useRef<Map<string, AbortController>>(new Map())
  const maxBytes = (limits?.max_upload_mb ?? FALLBACK_MAX_UPLOAD_MB) * 1_000_000

  const patch = useCallback((id: string, changes: Partial<BatchItem>) => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    )
  }, [])

  const addFiles = useCallback(
    (files: File[]) => {
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
          duplicateOf: null,
        }
        // Validacion en cliente ANTES de subir (upload.md).
        if (!isPdf(file)) return { ...base, status: 'rejected', errorCode: REJECT_NOT_PDF }
        if (file.size > maxBytes) return { ...base, status: 'rejected', errorCode: REJECT_TOO_LARGE }
        return base
      })
      setItems((current) => [...current, ...created])
      return created
    },
    [maxBytes],
  )

  const pollUntilSettled = useCallback(
    async (id: string, documentId: string) => {
      for (let attempt = 0; attempt < POLL_MAX_TRIES; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS))
        try {
          const fresh = await api.get<DocumentSummary>(`/documents/${documentId}`)
          if (fresh.status === 'ready' || fresh.status === 'printed' || fresh.status === 'queued') {
            patch(id, { status: 'ready', progress: 100, document: fresh })
            return
          }
          if (fresh.status === 'error') {
            patch(id, { status: 'error', errorCode: 'DOCUMENT_PROCESSING_FAILED', document: fresh })
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
    async (item: BatchItem, force: boolean) => {
      const controller = new AbortController()
      abortersRef.current.set(item.id, controller)
      patch(item.id, { status: 'uploading', progress: 0, errorCode: null, errorMessage: null })

      try {
        const result = await upload<UploadResponse>({
          path: '/documents/',
          file: item.file,
          fields: force ? { force: 'true' } : {},
          signal: controller.signal,
          onProgress: (progress) => patch(item.id, { progress }),
        })

        if (!result.document && result.duplicate_of) {
          patch(item.id, { status: 'duplicate', duplicateOf: result.duplicate_of, progress: 100 })
          return
        }

        const document = result.document
        if (!document) {
          patch(item.id, { status: 'error', errorCode: 'UPLOAD_EMPTY_RESPONSE' })
          return
        }

        if (document.status === 'ready' || document.status === 'printed') {
          patch(item.id, { status: 'ready', progress: 100, document })
          return
        }

        patch(item.id, { status: 'processing', progress: 100, document })
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
      void runItem(item, false)
    }
  }, [items, runItem])

  const retry = useCallback(
    (id: string) => {
      const item = items.find((entry) => entry.id === id)
      if (!item) return
      startedRef.current.add(id)
      void runItem(item, false)
    },
    [items, runItem],
  )

  /** "Subir igualmente" del aviso de duplicado. */
  const uploadAnyway = useCallback(
    (id: string) => {
      const item = items.find((entry) => entry.id === id)
      if (!item) return
      void runItem(item, true)
    },
    [items, runItem],
  )

  /** "Usar existente": adopta el documento ya archivado. */
  const useExisting = useCallback(
    (id: string) => {
      setItems((current) =>
        current.map((item) =>
          item.id === id && item.duplicateOf
            ? { ...item, status: 'ready', document: item.duplicateOf, progress: 100 }
            : item,
        ),
      )
    },
    [],
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
  const inFlight = items.some(
    (item) => item.status === 'uploading' || item.status === 'processing',
  )

  return {
    items,
    addFiles,
    retry,
    uploadAnyway,
    useExisting,
    remove,
    clear,
    readyItems,
    inFlight,
    counts: {
      total: items.length,
      ready: readyItems.length,
      errors: items.filter((item) => item.status === 'error' || item.status === 'rejected').length,
    },
    maxBytes,
  }
}
