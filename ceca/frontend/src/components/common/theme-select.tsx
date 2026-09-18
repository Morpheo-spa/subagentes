import { Moon, Sun, Desktop } from '@phosphor-icons/react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'
import { THEMES, useTheme, type Theme } from '@/lib/theme'

const ICONS = { light: Sun, dark: Moon, auto: Desktop } as const

export function ThemeSelect() {
  const { theme, setTheme } = useTheme()
  const { t } = useI18n()
  const Current = ICONS[theme]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="iconSm" aria-label={t('shell.theme')}>
          <Current size={18} aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={theme} onValueChange={(value) => setTheme(value as Theme)}>
          {THEMES.map((item) => {
            const IconComponent = ICONS[item]
            return (
              <DropdownMenuRadioItem key={item} value={item}>
                <IconComponent size={16} aria-hidden="true" />
                {t(`shell.themes.${item}`)}
              </DropdownMenuRadioItem>
            )
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
