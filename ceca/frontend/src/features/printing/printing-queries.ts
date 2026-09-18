import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request, requestBlob } from '@/lib/api'
import * as routes from '@/lib/routes'
import type {
  Acknowledgement,
  LabelTemplateCatalogResponse,
  PageResponse,
  PrintJobRead,
  QueueItemRead,
} from '@/lib/types'

/** La cola es persistente por usuario y tenant: vive en el servidor. */
export function usePrintQueue() {
  return useQuery({
    queryKey: ['printing', 'queue'],
    queryFn: () => request<PageResponse<QueueItemRead>>(routes.printingQueue()),
  })
}

export function usePrintTemplates() {
  return useQuery({
    queryKey: ['printing', 'templates'],
    queryFn: () => request<LabelTemplateCatalogResponse>(routes.printingTemplates()),
    staleTime: 10 * 60_000,
  })
}

export function usePrintJobs() {
  return useQuery({
    queryKey: ['printing', 'jobs'],
    queryFn: () => request<PageResponse<PrintJobRead>>(routes.printingJobs()),
  })
}

function useQueueInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['printing'] })
  }
}

export function useAddToQueue() {
  const invalidate = useQueueInvalidation()
  return useMutation({
    mutationFn: ({ documentIds, copies = 1 }: { documentIds: string[]; copies?: number }) =>
      request<PageResponse<QueueItemRead>>(routes.printingQueueAdd(), {
        body: { document_ids: documentIds, copies },
      }),
    onSuccess: invalidate,
  })
}

export function useRemoveFromQueue() {
  const invalidate = useQueueInvalidation()
  return useMutation({
    mutationFn: (itemId: string) =>
      request<Acknowledgement>(routes.printingQueueItem({ itemId })),
    onSuccess: invalidate,
  })
}

export function useClearQueue() {
  const invalidate = useQueueInvalidation()
  return useMutation({
    mutationFn: () => request<Acknowledgement>(routes.printingQueueClear()),
    onSuccess: invalidate,
  })
}

/** El orden completo, de delante a atras. */
export function useReorderQueue() {
  const invalidate = useQueueInvalidation()
  return useMutation({
    mutationFn: (itemIds: string[]) =>
      request<PageResponse<QueueItemRead>>(routes.printingQueueReorder(), {
        body: { item_ids: itemIds },
      }),
    onSuccess: invalidate,
  })
}

/** CLAUDE.md §3.11: nunca se imprime sin registrar antes el PrintJob. */
export function useCreatePrintJob() {
  const invalidate = useQueueInvalidation()
  return useMutation({
    mutationFn: (body: {
      template_code: string
      printer_name: string | null
      start_position: number
      item_ids?: string[] | null
    }) => request<PrintJobRead>(routes.printingJobCreate(), { body }),
    onSuccess: invalidate,
  })
}

export function useConfirmPrintJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      jobId,
      success,
      failureReason,
    }: {
      jobId: string
      success: boolean
      failureReason?: string | null
    }) =>
      request<PrintJobRead>(routes.printingJobConfirm({ jobId }), {
        body: { success, failure_reason: failureReason ?? null },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['printing'] })
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

/** El folio de etiquetas ya compuesto por el backend, listo para imprimir. */
export function fetchJobRender(jobId: string): Promise<Blob> {
  return requestBlob(routes.printingJobRender({ jobId }))
}
