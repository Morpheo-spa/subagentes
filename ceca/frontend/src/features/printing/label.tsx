import { shortId } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import { formatDate } from '@/lib/format'
import type { PrintQueueItem, PrintTemplate } from '@/lib/types'

/**
 * Etiqueta fisica (label-template.md).
 * El MISMO componente se usa en la vista previa y en `@media print`.
 * Solo negro sobre blanco; el QR codifica unicamente la URL publica corta.
 */
export function Label({
  item,
  template,
  tenantName,
}: {
  item: PrintQueueItem
  template: PrintTemplate
  tenantName: string | null
}) {
  const { t, locale } = useI18n()
  // QR >= 20mm, y nunca mas ancho que la etiqueta menos margenes.
  const qrMm = Math.max(20, Math.min(template.label_width_mm - 6, template.label_height_mm - 14))

  return (
    <div
      className="estampa-label flex flex-col justify-start gap-[1mm] overflow-hidden bg-print-paper p-[2mm] text-left text-print-ink"
      style={{ width: `${template.label_width_mm}mm`, height: `${template.label_height_mm}mm` }}
    >
      {item.qr_url ? (
        <img
          src={item.qr_url}
          alt={t('qr.alt', { name: item.original_name })}
          style={{ width: `${qrMm}mm`, height: `${qrMm}mm` }}
        />
      ) : (
        <div
          style={{ width: `${qrMm}mm`, height: `${qrMm}mm` }}
          className="border border-dashed border-print-ink"
          role="img"
          aria-label={t('qr.pending', { name: item.original_name })}
        />
      )}
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
        {item.original_name}
      </p>
      <p className="estampa-mono leading-tight" style={{ fontSize: '8pt' }}>
        {shortId(item.document_id)} · {formatDate(item.uploaded_at, locale)}
      </p>
      {tenantName ? (
        <p className="leading-tight" style={{ fontSize: '7pt' }}>
          {tenantName}
        </p>
      ) : null}
    </div>
  )
}
