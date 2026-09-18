import { QrImage } from '@/components/common/qr-image'
import { formatDate, shortId } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { LabelTemplateRead, QueueItemRead } from '@/lib/types'

/** Medidas por defecto si la plantilla no las declara (son opcionales). */
const DEFAULT_LABEL_MM = { width: 70, height: 37 }

export function labelSize(template: LabelTemplateRead) {
  return {
    width: template.label_width_mm ?? DEFAULT_LABEL_MM.width,
    height: template.label_height_mm ?? DEFAULT_LABEL_MM.height,
  }
}

/**
 * Etiqueta fisica (label-template.md).
 * Vista previa en pantalla: el folio que sale por la impresora lo compone el
 * backend en `GET /printing/jobs/{id}/render`, que es el que manda.
 * Solo negro sobre blanco; el QR codifica unicamente la URL publica corta.
 */
export function Label({
  item,
  template,
  siteName,
}: {
  item: QueueItemRead
  template: LabelTemplateRead
  siteName: string | null
}) {
  const { locale } = useI18n()
  const size = labelSize(template)
  const name = item.document?.original_filename ?? ''
  // QR >= 20mm, y nunca mas ancho que la etiqueta menos margenes.
  const qrMm = Math.max(20, Math.min(size.width - 6, size.height - 14))

  return (
    <div
      className="estampa-label flex flex-col justify-start gap-[1mm] overflow-hidden bg-print-paper p-[2mm] text-left text-print-ink"
      style={{ width: `${size.width}mm`, height: `${size.height}mm` }}
    >
      <QrImage
        documentId={item.document_id}
        documentName={name}
        size={Math.round(qrMm * 3.78)}
        className="h-auto w-auto"
      />
      <p
        className="font-semibold leading-tight"
        style={{
          fontSize: '9.5pt',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {name}
      </p>
      <p className="estampa-mono leading-tight" style={{ fontSize: '8pt' }}>
        {shortId(item.document_id)} ·{' '}
        {formatDate(item.document?.created_at ?? null, locale)}
      </p>
      {siteName ? (
        <p className="leading-tight" style={{ fontSize: '7pt' }}>
          {siteName}
        </p>
      ) : null}
    </div>
  )
}
