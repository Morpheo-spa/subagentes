import { Check, Copy } from '@phosphor-icons/react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/sonner'
import { useI18n } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export function CopyButton({
  value,
  label,
  successMessage,
  className,
  size = 'iconSm',
  withText = false,
}: {
  value: string
  /** Texto accesible del boton (solo icono -> aria-label). */
  label: string
  successMessage?: string
  className?: string
  size?: 'iconSm' | 'icon' | 'sm'
  withText?: boolean
}) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
      toast.success(successMessage ?? t('common.copied'))
    } catch {
      toast.error(t('common.copyFailed'))
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size={withText ? 'sm' : size}
      className={cn(className)}
      onClick={() => void copy()}
      aria-label={withText ? undefined : label}
      title={withText ? undefined : label}
    >
      {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
      {withText ? label : null}
    </Button>
  )
}
