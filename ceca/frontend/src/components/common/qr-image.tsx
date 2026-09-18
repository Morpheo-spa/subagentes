import { useQuery } from '@tanstack/react-query'
import { QrCode } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { requestBlob } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import * as routes from '@/lib/routes'
import { cn } from '@/lib/utils'

/**
 * El QR se sirve por `GET /documents/{id}/qr.png`, que va detras del bearer:
 * un `<img src>` no lleva cabeceras, asi que se descarga y se pinta desde un
 * object URL. MASTER §10: alt siempre "Codigo QR del documento {nombre}".
 */
export function QrImage({
  documentId,
  documentName,
  size,
  className,
}: {
  documentId: string | null
  documentName: string
  size: number
  className?: string
}) {
  const { t } = useI18n()
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  const qr = useQuery({
    queryKey: ['documents', documentId, 'qr'],
    queryFn: () => requestBlob(routes.documentQrPng({ documentId: documentId ?? '' })),
    enabled: Boolean(documentId),
    staleTime: Number.POSITIVE_INFINITY,
  })

  useEffect(() => {
    if (!qr.data) return
    const url = URL.createObjectURL(qr.data)
    setObjectUrl(url)
    return () => {
      URL.revokeObjectURL(url)
      setObjectUrl(null)
    }
  }, [qr.data])

  if (!objectUrl) {
    return (
      <div
        className={cn(
          'flex items-center justify-center rounded-sm border border-dashed border-border',
          className,
        )}
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
      src={objectUrl}
      width={size}
      height={size}
      // Reserva el hueco: sin salto de layout cuando carga (CLS < 0.1).
      style={{ width: size, height: size }}
      className={cn('block bg-print-paper', className)}
      alt={t('qr.alt', { name: documentName })}
      decoding="async"
    />
  )
}
