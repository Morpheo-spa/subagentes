import { Translate } from '@phosphor-icons/react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LOCALES, useI18n } from '@/lib/i18n'
import type { Locale } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * `compact`: en la barra superior y por debajo de `sm` solo se ve el icono
 * (el nombre del idioma sigue ahi para el lector de pantalla). Sin esto la
 * barra no cabia en 375px y toda la app tenia scroll horizontal.
 */
export function LanguageSelect({
  onChange,
  compact = false,
}: {
  onChange?: (locale: Locale) => void
  compact?: boolean
}) {
  const { locale, setLocale, t } = useI18n()

  return (
    <Select
      value={locale}
      onValueChange={(value) => {
        const next = value as Locale
        setLocale(next)
        onChange?.(next)
      }}
    >
      <SelectTrigger
        className={cn(
          'h-9 w-auto gap-2',
          compact ? 'min-w-0 px-2 sm:min-w-28 sm:px-3' : 'min-w-28',
        )}
        aria-label={t('shell.language')}
      >
        <Translate size={16} aria-hidden="true" className="shrink-0" />
        <SelectValue className={compact ? 'sr-only sm:not-sr-only' : undefined} />
      </SelectTrigger>
      <SelectContent>
        {LOCALES.map((item) => (
          <SelectItem key={item} value={item}>
            {t(`shell.languages.${item}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
