import { WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'

/** Muestra `message` y deja el `code` visible para soporte (rules/frontend.md). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n()
  const apiError = error instanceof ApiError ? error : null

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-md border border-destructive bg-destructive-surface px-6 py-10 text-center text-destructive-text"
    >
      <WarningCircle size={32} aria-hidden="true" />
      {/* Sin titulo generico encima: el mensaje de la API ya dice que ha
          pasado, y el codigo se conserva para soporte. */}
      <p className="max-w-prose text-base font-medium">
        {apiError?.message ?? t('errors.unexpected')}
      </p>
      {apiError ? (
        <p className="estampa-mono text-meta">{t('errors.code', { code: apiError.code })}</p>
      ) : null}
      {onRetry ? (
        <Button variant="outline" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      ) : null}
    </div>
  )
}
