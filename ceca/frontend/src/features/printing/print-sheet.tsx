import { Label } from './label'
import type { PrintQueueItem, PrintTemplate } from '@/lib/types'

export interface SheetPlacement {
  item: PrintQueueItem
}

/** Expande copias y respeta "empezar en la posicion N" (print-queue.md). */
export function paginate(
  items: PrintQueueItem[],
  template: PrintTemplate,
  startPosition: number,
): (PrintQueueItem | null)[][] {
  const perPage = template.mode === 'single' ? 1 : Math.max(1, template.columns * template.rows)
  const expanded: PrintQueueItem[] = []
  for (const item of items) {
    for (let copy = 0; copy < Math.max(1, item.copies); copy += 1) expanded.push(item)
  }

  const offset = template.mode === 'single' ? 0 : Math.min(Math.max(0, startPosition - 1), perPage - 1)
  const slots: (PrintQueueItem | null)[] = [...Array<null>(offset).fill(null), ...expanded]

  const pages: (PrintQueueItem | null)[][] = []
  for (let index = 0; index < slots.length; index += perPage) {
    const page = slots.slice(index, index + perPage)
    while (page.length < perPage) page.push(null)
    pages.push(page)
  }
  return pages.length ? pages : []
}

/**
 * Hoja lista para imprimir. Este DOM es el que ve el usuario en la vista previa
 * y el que sale por la impresora: `@media print` solo oculta lo de alrededor.
 */
export function PrintSheet({
  items,
  template,
  startPosition,
  tenantName,
  scale = 1,
}: {
  items: PrintQueueItem[]
  template: PrintTemplate
  startPosition: number
  tenantName: string | null
  scale?: number
}) {
  const pages = paginate(items, template, startPosition)

  return (
    <div className="estampa-print-root flex flex-col items-start gap-4">
      {pages.map((page, pageIndex) => (
        <div
          key={pageIndex}
          className="estampa-sheet-page origin-top-left border border-border bg-print-paper"
          style={{
            width: `${template.page_width_mm}mm`,
            height: `${template.page_height_mm}mm`,
            paddingTop: `${template.margin_top_mm}mm`,
            paddingLeft: `${template.margin_left_mm}mm`,
            display: 'grid',
            gridTemplateColumns: `repeat(${template.mode === 'single' ? 1 : template.columns}, ${template.label_width_mm}mm)`,
            gridAutoRows: `${template.label_height_mm}mm`,
            columnGap: `${template.gap_x_mm}mm`,
            rowGap: `${template.gap_y_mm}mm`,
            transform: scale === 1 ? undefined : `scale(${scale})`,
          }}
        >
          {page.map((item, slotIndex) =>
            item ? (
              <Label
                key={`${pageIndex}-${slotIndex}`}
                item={item}
                template={template}
                tenantName={tenantName}
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
