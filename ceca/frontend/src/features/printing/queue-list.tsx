import { ArrowDown, ArrowUp, DotsSixVertical, Trash } from '@phosphor-icons/react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label as FieldLabel } from '@/components/ui/label'
import { useI18n } from '@/lib/i18n'
import { truncateMiddle } from '@/lib/format'
import type { PrintQueueItem } from '@/lib/types'

/**
 * print-queue.md: reordenar con botones ↑↓ ADEMAS de drag.
 * El drag nunca es la unica via (WCAG 2.2).
 */
export function QueueList({
  items,
  onMove,
  onCopies,
  onRemove,
}: {
  items: PrintQueueItem[]
  onMove: (from: number, to: number) => void
  onCopies: (id: string, copies: number) => void
  onRemove: (item: PrintQueueItem) => void
}) {
  const { t } = useI18n()
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item, index) => (
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
          className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card p-3"
        >
          <DotsSixVertical size={20} aria-hidden="true" className="text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-medium" title={item.original_name}>
            {truncateMiddle(item.original_name, 36)}
          </span>

          <FieldLabel htmlFor={`copies-${item.id}`} className="text-meta text-muted-foreground">
            {t('printing.copies')}
          </FieldLabel>
          <Input
            id={`copies-${item.id}`}
            type="number"
            min={1}
            max={99}
            className="h-9 w-20"
            value={item.copies}
            onChange={(event) => onCopies(item.id, Math.max(1, Number(event.target.value) || 1))}
          />

          <Button
            variant="outline"
            size="iconSm"
            aria-label={t('printing.moveUp', { name: item.original_name })}
            disabled={index === 0}
            onClick={() => onMove(index, index - 1)}
          >
            <ArrowUp size={16} aria-hidden="true" />
          </Button>
          <Button
            variant="outline"
            size="iconSm"
            aria-label={t('printing.moveDown', { name: item.original_name })}
            disabled={index === items.length - 1}
            onClick={() => onMove(index, index + 1)}
          >
            <ArrowDown size={16} aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="iconSm"
            aria-label={t('printing.removeItem', { name: item.original_name })}
            onClick={() => onRemove(item)}
          >
            <Trash size={16} aria-hidden="true" />
          </Button>
        </li>
      ))}
    </ul>
  )
}
