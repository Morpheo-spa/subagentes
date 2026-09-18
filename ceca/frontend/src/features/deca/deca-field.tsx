import { FormDescription, FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import type { DecaFieldRead, DecaFieldType } from '@/lib/types'

/** `data_type` del catalogo -> `type` del input. Lo que no este, va como texto. */
const INPUT_TYPE: Partial<Record<DecaFieldType, string>> = {
  string: 'text',
  number: 'number',
  decimal: 'number',
  date: 'date',
  datetime: 'datetime-local',
}

function Control({
  field,
  value,
  onChange,
  onBlur,
  label,
}: {
  field: DecaFieldRead
  value: string
  onChange: (value: string) => void
  onBlur: () => void
  label: string
}) {
  const control = useFormControlProps()

  if (field.data_type === 'text') {
    return (
      <Textarea
        {...control}
        data-field={field.code}
        value={value}
        maxLength={field.max_length ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
      />
    )
  }

  if (field.data_type === 'enum') {
    return (
      <Select
        value={value}
        onValueChange={(next) => {
          onChange(next)
          onBlur()
        }}
      >
        <SelectTrigger {...control} data-field={field.code} aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {/* `choices` es una lista de codigos sin etiqueta: se pintan tal cual. */}
          {field.choices.map((choice) => (
            <SelectItem key={choice} value={choice}>
              {choice}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  const numeric = field.data_type === 'number' || field.data_type === 'decimal'
  return (
    <Input
      {...control}
      data-field={field.code}
      type={INPUT_TYPE[field.data_type] ?? 'text'}
      value={value}
      inputMode={numeric ? 'decimal' : undefined}
      maxLength={field.max_length ?? undefined}
      step={numeric ? 'any' : undefined}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
    />
  )
}

/** Un campo del catalogo DeCA. El catalogo manda; aqui no hay `if` por codigo. */
export function DecaField({
  field,
  value,
  error,
  onChange,
  onBlur,
}: {
  field: DecaFieldRead
  value: string
  error: string | null
  onChange: (value: string) => void
  onBlur: () => void
}) {
  const { t, pick } = useI18n()
  const label = pick(field, 'label')
  const help = pick(field, 'help')

  return (
    <FormField error={error} className={field.data_type === 'text' ? 'md:col-span-2' : undefined}>
      <FormLabel required={field.is_required} requiredLabel={t('common.required')}>
        {label}
      </FormLabel>
      <Control field={field} value={value} onChange={onChange} onBlur={onBlur} label={label} />
      {help || field.legal_reference ? (
        <FormDescription>
          {help}
          {field.legal_reference ? ` ${t('deca.legalRef', { ref: field.legal_reference })}` : ''}
        </FormDescription>
      ) : null}
    </FormField>
  )
}
