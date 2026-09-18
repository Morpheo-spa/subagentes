import { Label, labelSize } from './label'
import type { LabelTemplateRead, QueueItemRead } from '@/lib/types'

/** Cuantas etiquetas caben por hoja segun la plantilla del catalogo. */
export function slotsPerPage(template: LabelTemplateRead): number {
  if (template.layout === 'single') return 1
  if (template.slots_per_sheet) return Math.max(1, template.slots_per_sheet)
  return Math.max(1, (template.columns ?? 1) * (template.rows ?? 1))
}

/** Expande copias y respeta "empezar en la posicion N" (print-queue.md). */
export function paginate(
  items: QueueItemRead[],
  template: LabelTemplateRead,
  startPosition: number,
): (QueueItemRead | null)[][] {
  const perPage = slotsPerPage(template)
  const expanded: QueueItemRead[] = []
  for (const item of items) {
    for (let copy = 0; copy < Math.max(1, item.copies); copy += 1) expanded.push(item)
  }

  const offset = perPage === 1 ? 0 : Math.min(Math.max(0, startPosition - 1), perPage - 1)
  const slots: (QueueItemRead | null)[] = [...Array<null>(offset).fill(null), ...expanded]

  const pages: (QueueItemRead | null)[][] = []
  for (let index = 0; index < slots.length; index += perPage) {
    const page = slots.slice(index, index + perPage)
    while (page.length < perPage) page.push(null)
    pages.push(page)
  }
  return pages
}

/**
 * Vista previa de la hoja. La plantilla del backend NO trae tamano de pagina ni
 * margenes (`LabelTemplateRead`), asi que aqui solo se coloca la rejilla de
 * etiquetas con sus medidas reales; el folio definitivo lo compone el backend.
 */
export function PrintSheet({
  items,
  template,
  startPosition,
  siteName,
}: {
  items: QueueItemRead[]
  template: LabelTemplateRead
  startPosition: number
  siteName: string | null
}) {
  const pages = paginate(items, template, startPosition)
  const size = labelSize(template)
  const columns = template.layout === 'single' ? 1 : (template.columns ?? 1)

  return (
    <div className="estampa-print-root flex flex-col items-start gap-4">
      {pages.map((page, pageIndex) => (
        <div
          key={pageIndex}
          className="estampa-sheet-page origin-top-left border border-border bg-print-paper p-[5mm]"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${columns}, ${size.width}mm)`,
            gridAutoRows: `${size.height}mm`,
          }}
        >
          {page.map((item, slotIndex) =>
            item ? (
              <Label
                key={`${pageIndex}-${slotIndex}`}
                item={item}
                template={template}
                siteName={siteName}
              />
            ) : (
              <div key={`${pageIndex}-${slotIndex}`} aria-hidden="true" />
            ),
          )}
        </div>
      ))}
    </div>
  )
}
