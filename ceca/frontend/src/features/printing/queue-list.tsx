import { ArrowDown, ArrowUp, DotsSixVertical, Trash } from '@phosphor-icons/react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'
import { truncateMiddle } from '@/lib/format'
import type { QueueItemRead } from '@/lib/types'

/**
 * print-queue.md: reordenar con botones ↑↓ ADEMAS de drag.
 * El drag nunca es la unica via (WCAG 2.2).
 *
 * Sin tarjeta por item: la lista se lee mejor con aire y el asa de arrastre ya
 * marca donde empieza cada fila. Los tres botones son `ghost`: la fila no
 * necesita tres cajas.
 *
 * Las copias NO se editan aqui: el backend solo las acepta al anadir a la cola
 * (`QueueAddRequest.copies`), no tiene endpoint para cambiarlas despues.
 */
export function QueueList({
  items,
  onMove,
  onRemove,
}: {
  items: QueueItemRead[]
  onMove: (from: number, to: number) => void
  onRemove: (item: QueueItemRead) => void
}) {
  const { t } = useI18n()
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item, index) => {
        const name = item.document?.original_filename ?? item.document_id
        return (
          <li
            key={item.id}
            draggable
            onDragStart={() => setDragIndex(index)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (dragIndex !== null && dragIndex !== index) onMove(dragIndex, index)
              setDragIndex(null)
            }}
            onDragEnd={() => setDragIndex(null)}
            className="flex flex-wrap items-center gap-2 py-1"
          >
            <DotsSixVertical size={16} aria-hidden="true" className="text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate font-medium" title={name}>
              {truncateMiddle(name, 36)}
            </span>

            {/* "1 copias" no es informacion: la cuenta solo aparece si hay mas de una. */}
            {item.copies > 1 ? (
              <Badge variant="neutral">{t('printing.copiesCount', { count: item.copies })}</Badge>
            ) : null}

            <Button
              variant="ghost"
              size="iconSm"
              aria-label={t('printing.moveUp', { name })}
              disabled={index === 0}
              onClick={() => onMove(index, index - 1)}
            >
              <ArrowUp size={16} aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="iconSm"
              aria-label={t('printing.moveDown', { name })}
              disabled={index === items.length - 1}
              onClick={() => onMove(index, index + 1)}
            >
              <ArrowDown size={16} aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="iconSm"
              aria-label={t('printing.removeItem', { name })}
              onClick={() => onRemove(item)}
            >
              <Trash size={16} aria-hidden="true" />
            </Button>
          </li>
        )
      })}
    </ul>
  )
}
