import { CopyButton } from './copy-button'
import { shortId } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import { cn } from '@/lib/utils'

/** MASTER §4: el GUID va SIEMPRE en mono y con boton de copiar. */
export function Guid({
  value,
  short = false,
  className,
}: {
  value: string
  short?: boolean
  className?: string
}) {
  const { t } = useI18n()
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <code className="estampa-mono text-meta text-muted-foreground">
        {short ? shortId(value) : value}
      </code>
      <CopyButton value={value} label={t('common.copyGuid')} successMessage={t('common.guidCopied')} />
    </span>
  )
}
