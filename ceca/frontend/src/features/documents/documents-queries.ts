import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request, requestBlob, requestRaw } from '@/lib/api'
import * as routes from '@/lib/routes'
import type {
  Acknowledgement,
  DocumentFilters,
  DocumentHistoryResponse,
  DocumentRead,
  DocumentSummary,
  PageParams,
  PageResponse,
} from '@/lib/types'

export type DocumentListParams = PageParams & DocumentFilters

export function useDocuments(params: DocumentListParams) {
  return useQuery({
    queryKey: ['documents', 'list', params],
    queryFn: () =>
      request<PageResponse<DocumentSummary>>(routes.documentsList(), { query: { ...params } }),
    placeholderData: (previous) => previous, // sin salto de layout al paginar
  })
}

export function useDocument(documentId: string | null) {
  return useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => request<DocumentRead>(routes.documentRead({ documentId: documentId ?? '' })),
    enabled: Boolean(documentId),
  })
}

export function useDocumentHistory(documentId: string | null) {
  return useQuery({
    queryKey: ['documents', documentId, 'history'],
    queryFn: () =>
      request<DocumentHistoryResponse>(routes.documentHistory({ documentId: documentId ?? '' })),
    enabled: Boolean(documentId),
  })
}

/**
 * Retirar es de uno en uno: el backend no tiene endpoint de lote
 * (`POST /documents/{id}/withdraw`). Se recorre la seleccion y se informa de
 * los que fallan, en vez de fingir una operacion atomica que no existe.
 */
export function useWithdrawDocuments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ ids, reason }: { ids: string[]; reason: string }) => {
      const failed: string[] = []
      for (const documentId of ids) {
        try {
          await request<DocumentRead>(routes.documentWithdraw({ documentId }), { body: { reason } })
        } catch {
          failed.push(documentId)
        }
      }
      return { total: ids.length, failed }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useRevokeShare() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      request<Acknowledgement>(routes.documentShareRevoke({ documentId })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

/** Lo que el backend cuenta de la exportacion en sus cabeceras `X-Export-*`. */
export interface CsvExportResult {
  /** `X-Export-Truncated`: el filtro casaba mas filas de las que caben. */
  truncated: boolean
  /** `X-Export-Total`: filas que casaban con el filtro (no las exportadas). */
  total: number | null
  /** `X-Export-Row-Limit`: tope de filas por exportacion. */
  rowLimit: number | null
}

function headerInt(response: Response, name: string): number | null {
  const raw = response.headers.get(name)
  if (raw === null || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

/**
 * El CSV va detras del bearer, asi que no vale abrir la URL en otra pestana:
 * se descarga con la sesion en memoria y se entrega como fichero.
 *
 * `GET /documents/export.csv` esta limitado a `X-Export-Row-Limit` filas. Si
 * `X-Export-Truncated` es `true`, el fichero acaba en una fila
 * `# EXPORT_TRUNCATED max_rows=...`; aqui el CSV no se procesa (se entrega tal
 * cual), y la pagina avisa al usuario con el total y el tope.
 */
export async function downloadDocumentsCsv(params: DocumentListParams): Promise<CsvExportResult> {
  const response = await requestRaw(routes.documentsExportCsv(), {
    query: { ...params },
    accept: 'blob',
  })
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement('a')
  anchor.href = url
  anchor.download = 'documentos.csv'
  anchor.click()
  URL.revokeObjectURL(url)
  return {
    truncated: response.headers.get('X-Export-Truncated') === 'true',
    total: headerInt(response, 'X-Export-Total'),
    rowLimit: headerInt(response, 'X-Export-Row-Limit'),
  }
}

/** El PDF archivado, tambien por streaming autenticado. */
export function fetchDocumentFile(documentId: string): Promise<Blob> {
  return requestBlob(routes.documentFile({ documentId }))
}
