import { UploadSimple } from '@phosphor-icons/react'
import { useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * upload.md: zona unica a ancho completo, min-height 200px, borde discontinuo.
 * WCAG 2.2: el drag NUNCA es la unica via -> boton "Seleccionar archivos" visible.
 */
export function UploadDropZone({
  onFiles,
  maxBytes,
  disabled,
}: {
  onFiles: (files: File[]) => void
  maxBytes: number
  disabled?: boolean
}) {
  const { t, locale } = useI18n()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (disabled) return
    const files = Array.from(event.dataTransfer.files ?? [])
    if (files.length) onFiles(files)
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        'flex min-h-[200px] w-full flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-6 text-center transition-colors duration-200 ease-out',
        dragging ? 'border-secondary bg-muted' : 'border-border bg-card',
      )}
    >
      <UploadSimple size={32} aria-hidden="true" className="text-muted-foreground" />
      <p className="text-lead font-semibold">{t('upload.dropTitle')}</p>
      <p className="text-sm text-muted-foreground">
        {t('upload.dropHint', { size: formatBytes(maxBytes, locale) })}
      </p>
      <Button type="button" disabled={disabled} onClick={() => inputRef.current?.click()}>
        <UploadSimple size={20} aria-hidden="true" />
        {t('upload.selectFiles')}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? [])
          if (files.length) onFiles(files)
          event.target.value = ''
        }}
      />
    </div>
  )
}
