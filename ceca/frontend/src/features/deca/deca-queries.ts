import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from '@/lib/api'
import * as routes from '@/lib/routes'
import type {
  DecaCatalogResponse,
  DecaData,
  DecaValidationResult,
  DocumentRead,
} from '@/lib/types'

/** El catalogo de campos NO se hardcodea: viene de la API y se cachea. */
export function useDecaFields() {
  return useQuery({
    queryKey: ['deca', 'fields'],
    queryFn: () => request<DecaCatalogResponse>(routes.decaFields()),
    staleTime: 10 * 60_000,
  })
}

export function useDocumentDetail(documentId: string | undefined) {
  return useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => request<DocumentRead>(routes.documentRead({ documentId: documentId ?? '' })),
    enabled: Boolean(documentId),
  })
}

/** La verdad sobre "completo / incompleto" la da el backend, no el cliente. */
export function useValidateDeca() {
  return useMutation({
    mutationFn: (deca: DecaData) =>
      request<DecaValidationResult>(routes.decaValidate(), { body: { deca } }),
  })
}

/** Via conforme: el PDF nativo se genera desde los datos (docs/DECA.md §1). */
export function useGenerateDeca() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { deca: DecaData; filename?: string | null }) =>
      request<DocumentRead>(routes.documentsGenerate(), { body: payload }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

/** Completar o corregir metadatos de un documento que aun no es definitivo. */
export function usePatchDeca() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ documentId, deca }: { documentId: string; deca: DecaData }) =>
      request<DocumentRead>(routes.documentPatchDeca({ documentId }), { body: { deca } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

/** Modificar es crear una revision, con motivo obligatorio (docs/DECA.md §5). */
export function useCreateRevision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      documentId,
      changeReason,
      deca,
    }: {
      documentId: string
      changeReason: string
      deca: DecaData
    }) =>
      request<DocumentRead>(routes.documentRevisions({ documentId }), {
        body: { change_reason: changeReason, deca },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
