import { MagnifyingGlass, X } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import type { DocumentListParams } from '@/lib/types'

const STATUS_OPTIONS = ['all', 'ready', 'queued', 'printed', 'withdrawn', 'error'] as const

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
      <Input {...control} type={type} value={value} onChange={(event) => onChange(event.target.value)} />
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

  return (
    <section
      aria-label={t('documents.filters')}
      className="grid gap-4 rounded-lg border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <FormField>
        <TextFilter
          label={t('documents.search')}
          value={params.q ?? ''}
          onChange={(value) => onChange({ q: value, page: 1 })}
        />
      </FormField>

      <FormField>
        <FormLabel>{t('documents.status')}</FormLabel>
        <Select
          value={params.status ?? 'all'}
          onValueChange={(value) => onChange({ status: value === 'all' ? undefined : value, page: 1 })}
        >
          <SelectTrigger aria-label={t('documents.status')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {option === 'all' ? t('documents.allStatuses') : t(`status.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>

      <FormField>
        <TextFilter
          label={t('documents.uploadedFrom')}
          type="date"
          value={params.uploaded_from ?? ''}
          onChange={(value) => onChange({ uploaded_from: value || undefined, page: 1 })}
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

      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
        <Button variant="outline" size="sm" onClick={onReset}>
          <X size={16} aria-hidden="true" />
          {t('documents.resetFilters')}
        </Button>
        <p className="flex items-center gap-1 text-meta text-muted-foreground">
          <MagnifyingGlass size={14} aria-hidden="true" />
          {t('documents.searchHint')}
        </p>
      </div>
    </section>
  )
}
