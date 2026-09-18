import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { DecaFieldCatalog, DocumentDetail } from '@/lib/types'

/** El catalogo de campos NO se hardcodea: viene de la API y se cachea. */
export function useDecaFields() {
  return useQuery({
    queryKey: ['deca', 'fields'],
    queryFn: () => api.get<DecaFieldCatalog>('/deca/fields'),
    staleTime: 10 * 60_000,
  })
}

export function useDocumentDetail(documentId: string | undefined) {
  return useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => api.get<DocumentDetail>(`/documents/${documentId}`),
    enabled: Boolean(documentId),
  })
}
