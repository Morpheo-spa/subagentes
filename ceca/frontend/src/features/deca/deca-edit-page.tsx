import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { FormField, FormLabel, FormDescription, useFormControlProps } from '@/components/ui/form'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { DecaData } from '@/lib/types'
import { DecaForm } from './deca-form'
import {
  useCreateRevision,
  useDecaFields,
  useDocumentDetail,
  usePatchDeca,
} from './deca-queries'
import type { DecaValues } from './deca-validation'

/** `RevisionCreateRequest.change_reason`: min 3, max 500. */
const MIN_REASON = 3

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
        maxLength={500}
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
 *
 * Mientras el documento sigue en revision 0 y no es definitivo, el backend deja
 * completar los datos con `PATCH /documents/{id}/deca`; a partir de ahi exige
 * revision (`DECA_EDIT_REQUIRES_REVISION`).
 */
export default function DecaEditPage() {
  const { documentId } = useParams()
  const { t } = useI18n()
  const navigate = useNavigate()
  const catalog = useDecaFields()
  const detail = useDocumentDetail(documentId)
  const [changeReason, setChangeReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)

  const patch = usePatchDeca()
  const revise = useCreateRevision()

  if (catalog.isPending || detail.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-56 w-full" />
      </div>
    )
  }

  if (catalog.isError) {
    return <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
  }
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />

  const document = detail.data
  // Ya emitido: cualquier cambio es una revision nueva, con su motivo.
  const needsRevision = document.revision > 0 || document.status === 'ready'

  const initialValues: DecaValues = Object.fromEntries(
    Object.entries(document.deca).map(([key, value]) => [key, value === null ? '' : String(value)]),
  )

  const submit = async (values: DecaValues) => {
    const deca = values as DecaData
    if (needsRevision && changeReason.trim().length < MIN_REASON) {
      setReasonError(t('deca.changeReasonTooShort', { min: MIN_REASON }))
      return
    }
    setReasonError(null)
    try {
      if (needsRevision) {
        await revise.mutateAsync({
          documentId: document.id,
          changeReason: changeReason.trim(),
          deca,
        })
        toast.success(t('deca.revisionSaved'))
      } else {
        await patch.mutateAsync({ documentId: document.id, deca })
        toast.success(t('deca.valuesSaved'))
      }
      navigate(`/documents?document=${document.id}`)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected'))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t('deca.editTitle')}
        description={t('deca.editSubtitle', { name: document.original_filename })}
      />
      <DecaForm
        fields={catalog.data.fields}
        initialValues={initialValues}
        submitLabel={needsRevision ? t('deca.saveRevision') : t('deca.saveValues')}
        submitting={patch.isPending || revise.isPending}
        footer={
          needsRevision ? (
            <FormField error={reasonError}>
              <ChangeReasonField
                value={changeReason}
                onChange={setChangeReason}
                error={reasonError}
              />
            </FormField>
          ) : null
        }
        onSubmit={submit}
      />
    </div>
  )
}
