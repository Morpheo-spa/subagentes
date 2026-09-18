import { useMutation } from '@tanstack/react-query'
import { FileText } from '@phosphor-icons/react'
import { useState } from 'react'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { toast } from '@/components/ui/sonner'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { DocumentSummary } from '@/lib/types'
import { DecaForm } from './deca-form'
import { DecaResultCard } from './deca-result-card'
import { useDecaFields } from './deca-queries'
import type { DecaValues } from './deca-validation'

/**
 * "Generar DeCA": crea el PDF NATIVO desde los datos del formulario.
 * Es la unica via plenamente conforme (docs/DECA.md §1).
 */
export default function DecaGeneratePage() {
  const { t } = useI18n()
  const catalog = useDecaFields()
  const [created, setCreated] = useState<DocumentSummary | null>(null)
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})

  const generate = useMutation({
    mutationFn: (values: DecaValues) =>
      api.post<DocumentSummary>('/deca/generate', { values }),
    onSuccess: (document) => {
      setServerErrors({})
      setCreated(document)
      toast.success(t('deca.generatedToast'))
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        setServerErrors(error.fields ?? {})
        toast.error(error.message)
      } else {
        toast.error(t('errors.unexpected'))
      }
    },
  })

  const queuePrint = useMutation({
    mutationFn: (documentId: string) =>
      api.post('/printing/queue', { items: [{ document_id: documentId, copies: 1 }] }),
    onSuccess: () => toast.success(t('printing.addedToQueue', { count: 1 })),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('deca.generateTitle')} description={t('deca.generateSubtitle')} />

      <p className="rounded-md border border-border bg-muted p-4 text-sm text-muted-foreground">
        <FileText size={16} aria-hidden="true" className="mr-2 inline align-text-bottom" />
        {t('deca.nativeNotice')}
      </p>

      {catalog.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      ) : catalog.isError ? (
        <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
      ) : (
        <DecaForm
          fields={catalog.data.fields}
          submitLabel={t('deca.generateAction')}
          submitting={generate.isPending}
          serverErrors={serverErrors}
          onSubmit={async (values) => {
            await generate.mutateAsync(values).catch(() => undefined)
          }}
        />
      )}

      {created ? (
        <DecaResultCard
          document={created}
          queueing={queuePrint.isPending}
          onQueuePrint={() => queuePrint.mutate(created.id)}
        />
      ) : null}
    </div>
  )
}
