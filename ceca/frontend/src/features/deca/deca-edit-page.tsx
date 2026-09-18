import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { FormField, FormLabel, FormDescription, useFormControlProps } from '@/components/ui/form'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { DocumentSummary } from '@/lib/types'
import { DecaForm } from './deca-form'
import { useDecaFields, useDocumentDetail } from './deca-queries'
import type { DecaValues } from './deca-validation'

function ChangeReasonField({
  value,
  onChange,
  error,
}: {
  value: string
  onChange: (value: string) => void
  error: string | null
}) {
  const { t } = useI18n()
  const control = useFormControlProps()
  return (
    <>
      <FormLabel required requiredLabel={t('common.required')}>
        {t('deca.changeReason')}
      </FormLabel>
      <Textarea
        {...control}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={Boolean(error)}
      />
      <FormDescription>{t('deca.changeReasonHelp')}</FormDescription>
    </>
  )
}

/**
 * Modificar un DeCA NO es editar en sitio: crea una revision nueva con
 * `change_reason` obligatorio y conserva la anterior (docs/DECA.md §5).
 */
export default function DecaEditPage() {
  const { documentId } = useParams()
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const catalog = useDecaFields()
  const detail = useDocumentDetail(documentId)
  const [changeReason, setChangeReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})

  const isRevision = (detail.data?.revision ?? 0) > 0

  const save = useMutation({
    mutationFn: (values: DecaValues) =>
      api.post<DocumentSummary>(`/documents/${documentId}/revisions`, {
        values,
        change_reason: changeReason || null,
      }),
    onSuccess: () => {
      toast.success(t('deca.revisionSaved'))
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      navigate(`/documents?document=${documentId}`)
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

  if (catalog.isPending || detail.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-56 w-full" />
      </div>
    )
  }

  if (catalog.isError) return <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t('deca.editTitle')}
        description={t('deca.editSubtitle', { name: detail.data.original_name })}
      />
      <DecaForm
        fields={catalog.data.fields}
        initialValues={detail.data.deca_values}
        submitLabel={isRevision ? t('deca.saveRevision') : t('deca.saveValues')}
        submitting={save.isPending}
        serverErrors={serverErrors}
        footer={
          isRevision ? (
            <FormField error={reasonError}>
              <ChangeReasonField value={changeReason} onChange={setChangeReason} error={reasonError} />
            </FormField>
          ) : null
        }
        onSubmit={async (values) => {
          if (isRevision && !changeReason.trim()) {
            setReasonError(t('deca.validation.required'))
            return
          }
          setReasonError(null)
          await save.mutateAsync(values).catch(() => undefined)
        }}
      />
    </div>
  )
}
