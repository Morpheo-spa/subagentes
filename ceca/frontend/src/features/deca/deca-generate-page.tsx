import { FileText } from '@phosphor-icons/react'
import { useState } from 'react'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { toast } from '@/components/ui/sonner'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { DecaData, DocumentRead } from '@/lib/types'
import { useAddToQueue } from '@/features/printing/printing-queries'
import { DecaForm } from './deca-form'
import { DecaResultCard } from './deca-result-card'
import { useDecaFields, useGenerateDeca, useValidateDeca } from './deca-queries'
import type { DecaValues } from './deca-validation'

/** Falta un obligatorio: el documento se archiva `incompleto`, no se rechaza. */
const REQUIRED_CODE = 'DECA_FIELD_REQUIRED'

/**
 * "Generar DeCA": crea el PDF NATIVO desde los datos del formulario.
 * Es la unica via plenamente conforme (docs/DECA.md §1).
 */
export default function DecaGeneratePage() {
  const { t } = useI18n()
  const catalog = useDecaFields()
  const [created, setCreated] = useState<DocumentRead | null>(null)
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})

  const validate = useValidateDeca()
  const generate = useGenerateDeca()
  const queuePrint = useAddToQueue()

  const submit = async (values: DecaValues) => {
    const deca = values as DecaData
    try {
      // La verdad sobre los datos la da el backend (`POST /deca/validate`).
      const verdict = await validate.mutateAsync(deca)
      setServerErrors(
        Object.fromEntries(verdict.errors.map((error) => [error.field, error.message])),
      )
      const blocking = verdict.errors.filter((error) => error.code !== REQUIRED_CODE)
      if (blocking.length > 0) {
        toast.error(blocking[0].message)
        return
      }

      const document = await generate.mutateAsync({ deca })
      setCreated(document)
      toast.success(
        document.deca_status === 'incompleto'
          ? t('deca.generatedIncompleteToast')
          : t('deca.generatedToast'),
      )
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected'))
    }
  }

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
          submitting={generate.isPending || validate.isPending}
          serverErrors={serverErrors}
          onSubmit={submit}
        />
      )}

      {created ? (
        <DecaResultCard
          document={created}
          queueing={queuePrint.isPending}
          onQueuePrint={() =>
            queuePrint.mutate(
              { documentIds: [created.id] },
              {
                onSuccess: () => toast.success(t('printing.addedToQueue', { count: 1 })),
                onError: (error) =>
                  toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
              },
            )
          }
        />
      ) : null}
    </div>
  )
}
