import { FormDescription, FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import type { DecaFieldDefinition } from '@/lib/types'

const INPUT_TYPE: Record<string, string> = {
  text: 'text',
  number: 'number',
  date: 'date',
  nif: 'text',
  plate: 'text',
}

function Control({
  definition,
  value,
  onChange,
  onBlur,
  label,
}: {
  definition: DecaFieldDefinition
  value: string
  onChange: (value: string) => void
  onBlur: () => void
  label: string
}) {
  const control = useFormControlProps()
  const { pick } = useI18n()

  if (definition.type === 'textarea') {
    return (
      <Textarea
        {...control}
        data-field={definition.code}
        value={value}
        maxLength={definition.max_length ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
      />
    )
  }

  if (definition.type === 'select') {
    return (
      <Select value={value} onValueChange={(next) => { onChange(next); onBlur() }}>
        <SelectTrigger {...control} data-field={definition.code} aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(definition.options ?? []).map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {pick(option, 'label')}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  return (
    <Input
      {...control}
      data-field={definition.code}
      type={INPUT_TYPE[definition.type] ?? 'text'}
      value={value}
      inputMode={definition.type === 'number' ? 'decimal' : undefined}
      maxLength={definition.max_length ?? undefined}
      step={definition.type === 'number' ? 'any' : undefined}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
    />
  )
}

/** Un campo del catalogo DeCA. El catalogo manda; aqui no hay `if` por codigo. */
export function DecaField({
  definition,
  value,
  error,
  onChange,
  onBlur,
}: {
  definition: DecaFieldDefinition
  value: string
  error: string | null
  onChange: (value: string) => void
  onBlur: () => void
}) {
  const { t, pick } = useI18n()
  const label = pick(definition, 'label')
  const help = pick(definition, 'help')

  return (
    <FormField error={error} className={definition.type === 'textarea' ? 'md:col-span-2' : undefined}>
      <FormLabel required={definition.required} requiredLabel={t('common.required')}>
        {label}
      </FormLabel>
      <Control
        definition={definition}
        value={value}
        onChange={onChange}
        onBlur={onBlur}
        label={label}
      />
      {help || definition.legal_ref ? (
        <FormDescription>
          {help}
          {definition.legal_ref
            ? ` ${t('deca.legalRef', { ref: definition.legal_ref })}`
            : ''}
        </FormDescription>
      ) : null}
    </FormField>
  )
}
