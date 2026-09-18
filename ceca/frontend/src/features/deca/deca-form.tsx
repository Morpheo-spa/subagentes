import { useForm } from '@tanstack/react-form'
import { useRef } from 'react'
import { FormErrorSummary } from '@/components/ui/form'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'
import type { DecaFieldDefinition } from '@/lib/types'
import { DecaField } from './deca-field'
import { groupFields, validateAll, validateField, type DecaValues } from './deca-validation'

export interface DecaFormProps {
  fields: DecaFieldDefinition[]
  initialValues?: DecaValues
  submitLabel: string
  submitting?: boolean
  /** Errores por campo devueltos por la API (`detail.fields`). */
  serverErrors?: Record<string, string>
  onSubmit: (values: DecaValues) => void | Promise<void>
  footer?: React.ReactNode
}

export function DecaForm({
  fields,
  initialValues,
  submitLabel,
  submitting,
  serverErrors,
  onSubmit,
  footer,
}: DecaFormProps) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLFormElement>(null)
  const groups = groupFields(fields)

  const defaultValues: DecaValues = Object.fromEntries(
    fields.map((field) => [field.code, initialValues?.[field.code] ?? '']),
  )

  const form = useForm({
    defaultValues,
    onSubmit: async ({ value }) => {
      await onSubmit(value)
    },
  })

  /** MASTER §9: al enviar con errores, foco al primero. */
  const focusField = (code: string) => {
    const element = containerRef.current?.querySelector<HTMLElement>(`[data-field="${code}"]`)
    element?.focus()
    element?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  const summaryErrors = (values: DecaValues) =>
    Object.entries(validateAll(fields, values)).map(([code, issue]) => {
      const definition = fields.find((field) => field.code === code)
      return {
        field: code,
        label: definition ? (definition.label_es ?? code) : code,
        message: t(issue.key, issue.params),
      }
    })

  return (
    <form
      ref={containerRef}
      noValidate
      className="flex flex-col gap-6"
      onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        const values = form.state.values as DecaValues
        const errors = validateAll(fields, values)
        const first = Object.keys(errors)[0]
        if (first) {
          void form.validateAllFields('submit')
          focusField(first)
          return
        }
        void form.handleSubmit()
      }}
    >
      <form.Subscribe selector={(state) => state.values}>
        {(values) => (
          <FormErrorSummary
            title={t('deca.errorSummary')}
            errors={
              form.state.submissionAttempts > 0 ? summaryErrors(values as DecaValues) : []
            }
            onFocusField={focusField}
          />
        )}
      </form.Subscribe>

      {groups.map((group) => (
        <fieldset key={group.group} className="rounded-lg border border-border bg-card p-4">
          {/* docs/DECA.md §3: cargador y transportista, expresos y diferenciados. */}
          <legend className="px-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {t(`deca.groups.${group.group}`)}
          </legend>
          <p className="mb-4 text-meta text-muted-foreground">
            {t(`deca.groupHints.${group.group}`)}
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {group.fields.map((definition) => (
              <form.Field
                key={definition.code}
                name={definition.code}
                validators={{
                  // Validacion inline al blur (MASTER §9).
                  onBlur: ({ value }) => {
                    const issue = validateField(definition, value as string)
                    return issue ? t(issue.key, issue.params) : undefined
                  },
                }}
              >
                {(field) => (
                  <DecaField
                    definition={definition}
                    value={(field.state.value as string) ?? ''}
                    error={
                      serverErrors?.[definition.code] ??
                      (field.state.meta.errors[0] as string | undefined) ??
                      null
                    }
                    onChange={(next) => field.handleChange(next)}
                    onBlur={field.handleBlur}
                  />
                )}
              </form.Field>
            ))}
          </div>
        </fieldset>
      ))}

      {footer}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={submitting}>
          {submitting ? t('common.saving') : submitLabel}
        </Button>
      </div>
    </form>
  )
}
