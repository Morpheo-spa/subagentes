import { Translate } from '@phosphor-icons/react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LOCALES, useI18n } from '@/lib/i18n'
import type { Locale } from '@/lib/types'

export function LanguageSelect({ onChange }: { onChange?: (locale: Locale) => void }) {
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
      <SelectTrigger className="h-9 w-auto min-w-28 gap-2" aria-label={t('shell.language')}>
        <Translate size={16} aria-hidden="true" />
        <SelectValue />
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
