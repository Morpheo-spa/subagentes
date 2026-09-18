import { QrCode } from '@phosphor-icons/react'
import { useI18n } from '@/lib/i18n'
import { cn } from '@/lib/utils'

/** MASTER §10: alt siempre "Codigo QR del documento {nombre}". */
export function QrImage({
  src,
  documentName,
  size,
  className,
}: {
  src: string | null
  documentName: string
  size: number
  className?: string
}) {
  const { t } = useI18n()

  if (!src) {
    return (
      <div
        className={cn('flex items-center justify-center rounded-sm border border-dashed border-border', className)}
        style={{ width: size, height: size }}
        role="img"
        aria-label={t('qr.pending', { name: documentName })}
      >
        <QrCode size={Math.min(24, size / 2)} aria-hidden="true" className="text-muted-foreground" />
      </div>
    )
  }

  return (
    <img
      src={src}
      width={size}
      height={size}
      // Reserva el hueco: sin salto de layout cuando carga (CLS < 0.1).
      style={{ width: size, height: size }}
      className={cn('block bg-print-paper', className)}
      alt={t('qr.alt', { name: documentName })}
      loading="lazy"
      decoding="async"
    />
  )
}
