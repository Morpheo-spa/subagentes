/**
 * Primitivas de formulario sobre TanStack Form (no react-hook-form).
 * Se encargan del cableado accesible: label visible siempre, `aria-describedby`,
 * `aria-invalid` y el error pegado al campo (MASTER §6 y §9).
 */
import { WarningCircle } from '@phosphor-icons/react'
import { createContext, useContext, useId, type ReactNode } from 'react'
import { Label } from './label'
import { cn } from '@/lib/utils'

interface FieldContextValue {
  id: string
  descriptionId: string
  messageId: string
  invalid: boolean
}

const FieldContext = createContext<FieldContextValue | null>(null)

function useField(): FieldContextValue {
  const ctx = useContext(FieldContext)
  if (!ctx) throw new Error('Componente de formulario fuera de <FormField>')
  return ctx
}

export interface FormFieldProps {
  /** Mensaje de error ya traducido (viene del validador o de la API). */
  error?: string | null
  children: ReactNode
  className?: string
}

export function FormField({ error, children, className }: FormFieldProps) {
  const id = useId()
  const value: FieldContextValue = {
    id,
    descriptionId: `${id}-description`,
    messageId: `${id}-message`,
    invalid: Boolean(error),
  }
  return (
    <FieldContext.Provider value={value}>
      <div className={cn('flex flex-col gap-2', className)}>
        {children}
        {error ? <FormMessage>{error}</FormMessage> : null}
      </div>
    </FieldContext.Provider>
  )
}

export function FormLabel({
  children,
  required,
  requiredLabel,
  className,
}: {
  children: ReactNode
  required?: boolean
  /** Texto accesible para el asterisco (i18n). */
  requiredLabel?: string
  className?: string
}) {
  const { id, invalid } = useField()
  return (
    <Label htmlFor={id} className={cn(invalid && 'text-destructive-text', className)}>
      {children}
      {required ? (
        <>
          <span aria-hidden="true" className="ml-1 text-destructive-text">
            *
          </span>
          <span className="sr-only">{requiredLabel}</span>
        </>
      ) : null}
    </Label>
  )
}

/** Devuelve los props que hay que esparcir sobre el control. */
export function useFormControlProps() {
  const { id, descriptionId, messageId, invalid } = useField()
  return {
    id,
    'aria-invalid': invalid,
    'aria-describedby': invalid ? `${descriptionId} ${messageId}` : descriptionId,
  } as const
}

export function FormDescription({ children }: { children: ReactNode }) {
  const { descriptionId } = useField()
  return (
    <p id={descriptionId} className="text-meta text-muted-foreground">
      {children}
    </p>
  )
}

export function FormMessage({ children }: { children: ReactNode }) {
  const { messageId } = useField()
  return (
    <p
      id={messageId}
      role="alert"
      className="flex items-start gap-1.5 text-sm font-medium text-destructive-text"
    >
      <WarningCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </p>
  )
}

/** Resumen de errores arriba, solo si hay mas de uno (MASTER §9). */
export function FormErrorSummary({
  title,
  errors,
  onFocusField,
}: {
  title: string
  errors: { field: string; label: string; message: string }[]
  onFocusField?: (field: string) => void
}) {
  if (errors.length < 2) return null
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive bg-destructive-surface p-4 text-destructive-text"
    >
      <p className="flex items-center gap-2 font-semibold">
        <WarningCircle size={20} aria-hidden="true" />
        {title}
      </p>
      <ul className="mt-2 list-inside list-disc space-y-1 text-sm">
        {errors.map((error) => (
          <li key={error.field}>
            <button
              type="button"
              className="cursor-pointer underline underline-offset-2 hover:no-underline"
              onClick={() => onFocusField?.(error.field)}
            >
              {error.label}: {error.message}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
