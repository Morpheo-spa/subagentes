import { useForm } from '@tanstack/react-form'
import { PencilSimple } from '@phosphor-icons/react'
import { useRef, type ReactNode } from 'react'
import { FormErrorSummary } from '@/components/ui/form'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'
import type { DecaFieldRead } from '@/lib/types'
import { DecaField } from './deca-field'
import { groupFields, missingRequired } from './deca-catalog'
import {
  partiesAreDistinct,
  validateAll,
  validateField,
  type DecaValues,
} from './deca-validation'

export interface DecaFormProps {
  fields: DecaFieldRead[]
  initialValues?: DecaValues
  submitLabel: string
  submitting?: boolean
  /** Errores por campo devueltos por `POST /deca/validate`. */
  serverErrors?: Record<string, string>
  onSubmit: (values: DecaValues) => void | Promise<void>
  footer?: ReactNode
}

/** Falta un obligatorio -> `incompleto`, que no bloquea. Lo demas, si. */
const REQUIRED_KEY = 'deca.validation.required'

export function DecaForm({
  fields,
  initialValues,
  submitLabel,
  submitting,
  serverErrors,
  onSubmit,
  footer,
}: DecaFormProps) {
  const { t, pick } = useI18n()
  const containerRef = useRef<HTMLFormElement>(null)
  const blocks = groupFields(fields)

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

  const blockingErrors = (values: DecaValues) =>
    Object.entries(validateAll(fields, values)).filter(([, issue]) => issue.key !== REQUIRED_KEY)

  const summaryErrors = (values: DecaValues) =>
    blockingErrors(values).map(([code, issue]) => {
      const definition = fields.find((field) => field.code === code)
      return {
        field: code,
        label: definition ? pick(definition, 'label') : code,
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
        // Un dato mal escrito si para; que falte un obligatorio, no:
        // el documento se archiva y queda `incompleto` (deca-form.md).
        const first = blockingErrors(values)[0]?.[0]
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

      {blocks.map((entry) => (
        <fieldset key={entry.block} className="rounded-md border border-border bg-card p-4">
          {/* docs/DECA.md §3: cargador y transportista, expresos y diferenciados. */}
          <legend className="px-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {t(`deca.blocks.${entry.block}`)}
          </legend>
          <p className="mb-4 text-meta text-muted-foreground">
            {t(`deca.blockHints.${entry.block}`)}
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {entry.fields.map((field) => (
              <form.Field
                key={field.code}
                name={field.code}
                validators={{
                  // Validacion inline al blur (MASTER §9).
                  onBlur: ({ value }) => {
                    const issue = validateField(field, value as string)
                    return issue ? t(issue.key, issue.params) : undefined
                  },
                }}
              >
                {(control) => (
                  <DecaField
                    field={field}
                    value={(control.state.value as string) ?? ''}
                    error={
                      serverErrors?.[field.code] ??
                      (control.state.meta.errors[0] as string | undefined) ??
                      null
                    }
                    onChange={(next) => control.handleChange(next)}
                    onBlur={control.handleBlur}
                  />
                )}
              </form.Field>
            ))}
          </div>
        </fieldset>
      ))}

      {footer}

      <form.Subscribe selector={(state) => state.values}>
        {(values) => {
          const current = values as DecaValues
          const missing = missingRequired(fields, current)
          const sameParty = !partiesAreDistinct(fields, current)
          return (
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={submitting}>
                {submitting ? t('common.saving') : submitLabel}
              </Button>

              {/* Barra de estado: "faltan N" no impide guardar, avisa. */}
              <p role="status" className="flex items-center gap-1.5 text-sm text-warning-text">
                {missing.length > 0 ? (
                  <>
                    <PencilSimple size={16} aria-hidden="true" />
                    {t('deca.incompleteNotice', { count: missing.length })}
                  </>
                ) : null}
              </p>

              {sameParty ? (
                <p role="alert" className="text-sm text-destructive-text">
                  {t('deca.partiesNotDistinct')}
                </p>
              ) : null}
            </div>
          )
        }}
      </form.Subscribe>
    </form>
  )
}
