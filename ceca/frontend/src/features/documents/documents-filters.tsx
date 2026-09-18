import { X } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import type { ComplianceStatus, DocumentStatus } from '@/lib/types'
import type { DocumentListParams } from './documents-queries'

/** Los valores reales de `DocumentStatus` (app/models/documents.py). */
const STATUS_OPTIONS: DocumentStatus[] = ['pending', 'processing', 'ready', 'withdrawn', 'failed']

/** `ComplianceStatus`: separa "sirve como DeCA" de "esta archivado". */
const COMPLIANCE_OPTIONS: ComplianceStatus[] = [
  'compliant',
  'incomplete',
  'not_a_deca',
  'superseded',
]

const ALL = 'all'

function TextFilter({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string
  value: string
  type?: string
  onChange: (value: string) => void
}) {
  const control = useFormControlProps()
  return (
    <>
      <FormLabel>{label}</FormLabel>
      <Input
        {...control}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </>
  )
}

export function DocumentsFilters({
  params,
  onChange,
  onReset,
}: {
  params: DocumentListParams
  onChange: (patch: Partial<DocumentListParams>) => void
  onReset: () => void
}) {
  const { t } = useI18n()

  // Sin tarjeta: los filtros se separan del listado con aire, no con un marco.
  return (
    <section
      aria-label={t('documents.filters')}
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <FormField>
        <TextFilter
          label={t('documents.search')}
          value={params.search ?? ''}
          onChange={(value) => onChange({ search: value || undefined, page: 1 })}
        />
      </FormField>

      <FormField>
        <FormLabel>{t('documents.status')}</FormLabel>
        <Select
          value={params.status ?? ALL}
          onValueChange={(value) =>
            onChange({ status: value === ALL ? undefined : (value as DocumentStatus), page: 1 })
          }
        >
          <SelectTrigger aria-label={t('documents.status')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('documents.allStatuses')}</SelectItem>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`status.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>

      <FormField>
        <FormLabel>{t('documents.compliance')}</FormLabel>
        <Select
          value={params.compliance_status ?? ALL}
          onValueChange={(value) =>
            onChange({
              compliance_status: value === ALL ? undefined : (value as ComplianceStatus),
              page: 1,
            })
          }
        >
          <SelectTrigger aria-label={t('documents.compliance')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('documents.allCompliance')}</SelectItem>
            {COMPLIANCE_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`compliance.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>

      <FormField>
        <TextFilter
          label={t('documents.uploadedFrom')}
          type="date"
          value={params.created_from ?? ''}
          onChange={(value) => onChange({ created_from: value || undefined, page: 1 })}
        />
      </FormField>

      <FormField>
        <TextFilter
          label={t('documents.expiresBefore')}
          type="date"
          value={params.expires_before ?? ''}
          onChange={(value) => onChange({ expires_before: value || undefined, page: 1 })}
        />
      </FormField>

      {/* Sin nota de ayuda: la etiqueta del campo ya dice que se busca por
          nombre o GUID, y el icono junto al texto solo adornaba. */}
      <div className="flex items-end sm:col-span-2 lg:col-span-4">
        <Button variant="outline" size="sm" onClick={onReset}>
          <X size={16} aria-hidden="true" />
          {t('documents.resetFilters')}
        </Button>
      </div>
    </section>
  )
}
