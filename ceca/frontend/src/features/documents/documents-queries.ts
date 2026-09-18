import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { DocumentDetail, DocumentListParams, DocumentSummary, Paginated } from '@/lib/types'

export function useDocuments(params: DocumentListParams) {
  return useQuery({
    queryKey: ['documents', 'list', params],
    queryFn: () =>
      api.get<Paginated<DocumentSummary>>('/documents', {
        query: { ...params },
      }),
    placeholderData: (previous) => previous, // sin salto de layout al paginar
  })
}

export function useDocument(documentId: string | null) {
  return useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => api.get<DocumentDetail>(`/documents/${documentId}`),
    enabled: Boolean(documentId),
  })
}

export function useQueueForPrint() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (items: { document_id: string; copies: number }[]) =>
      api.post('/printing/queue', { items }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing', 'queue'] })
    },
  })
}

export function useWithdrawDocuments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ids, reason }: { ids: string[]; reason: string }) =>
      api.post('/documents/withdraw', { document_ids: ids, reason }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useRevokeToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) => api.post(`/documents/${documentId}/revoke-token`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
