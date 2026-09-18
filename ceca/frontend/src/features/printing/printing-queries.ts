import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { PrinterRef, PrintJob, PrintQueueItem, PrintTemplate } from '@/lib/types'

/** La cola es persistente por usuario y tenant: vive en el servidor. */
export function usePrintQueue() {
  return useQuery({
    queryKey: ['printing', 'queue'],
    queryFn: () => api.get<{ items: PrintQueueItem[] }>('/printing/queue'),
  })
}

export function usePrintTemplates() {
  return useQuery({
    queryKey: ['printing', 'templates'],
    queryFn: () => api.get<{ items: PrintTemplate[] }>('/printing/templates'),
    staleTime: 10 * 60_000,
  })
}

export function usePrinters() {
  return useQuery({
    queryKey: ['printing', 'printers'],
    queryFn: () => api.get<{ items: PrinterRef[] }>('/printing/printers'),
    staleTime: 10 * 60_000,
  })
}

export function useUpdateQueue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (items: { id: string; copies: number; position: number }[]) =>
      api.put('/printing/queue', { items }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing', 'queue'] })
    },
  })
}

export function useRemoveFromQueue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => api.delete(`/printing/queue/${itemId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing', 'queue'] })
    },
  })
}

/** CLAUDE.md §3.11: nunca se imprime sin registrar antes el PrintJob. */
export function useCreatePrintJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      printer_id: string | null
      template_id: string
      start_position: number
      items: { queue_item_id: string; copies: number }[]
    }) => api.post<PrintJob>('/printing/jobs', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing'] })
    },
  })
}

export function useConfirmPrintJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, ok }: { jobId: string; ok: boolean }) =>
      api.post(`/printing/jobs/${jobId}/confirm`, { ok }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing'] })
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
