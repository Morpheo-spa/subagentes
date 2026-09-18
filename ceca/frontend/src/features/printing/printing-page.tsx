import { Printer, Stack } from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { EmptyState } from '@/components/common/empty-state'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label as FieldLabel } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatNumber } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { PrintQueueItem, PrintTemplate } from '@/lib/types'
import { paginate, PrintSheet } from './print-sheet'
import { QueueList } from './queue-list'
import {
  useConfirmPrintJob,
  useCreatePrintJob,
  usePrinters,
  usePrintQueue,
  usePrintTemplates,
  useRemoveFromQueue,
  useUpdateQueue,
} from './printing-queries'

const PRINTER_KEY = 'estampa.printer'
const TEMPLATE_KEY = 'estampa.template'

function StartPositionField({
  value,
  onChange,
  max,
}: {
  value: number
  onChange: (value: number) => void
  max: number
}) {
  const { t } = useI18n()
  const control = useFormControlProps()
  return (
    <>
      <FormLabel>{t('printing.startPosition')}</FormLabel>
      <Input
        {...control}
        type="number"
        min={1}
        max={max}
        value={value}
        onChange={(event) => onChange(Math.min(max, Math.max(1, Number(event.target.value) || 1)))}
      />
    </>
  )
}

export default function PrintingPage() {
  const { t, locale, pick } = useI18n()
  const { user } = useAuth()
  const queue = usePrintQueue()
  const templates = usePrintTemplates()
  const printers = usePrinters()
  const updateQueue = useUpdateQueue()
  const removeItem = useRemoveFromQueue()
  const createJob = useCreatePrintJob()
  const confirmJob = useConfirmPrintJob()

  const [items, setItems] = useState<PrintQueueItem[]>([])
  const [mode, setMode] = useState<'single' | 'grid'>('grid')
  const [templateId, setTemplateId] = useState<string>('')
  const [printerId, setPrinterId] = useState<string>('')
  const [startPosition, setStartPosition] = useState(1)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingRemoval, setPendingRemoval] = useState<PrintQueueItem | null>(null)
  const [printedJobId, setPrintedJobId] = useState<string | null>(null)

  useEffect(() => {
    if (queue.data) setItems(queue.data.items)
  }, [queue.data])

  // Recordar impresora y plantilla (print-queue.md).
  useEffect(() => {
    try {
      const storedPrinter = window.localStorage.getItem(PRINTER_KEY)
      const storedTemplate = window.localStorage.getItem(TEMPLATE_KEY)
      if (storedPrinter) setPrinterId(storedPrinter)
      if (storedTemplate) setTemplateId(storedTemplate)
    } catch {
      /* preferencia no persistible */
    }
  }, [])

  const available = useMemo(
    () => (templates.data?.items ?? []).filter((template) => template.mode === mode),
    [templates.data, mode],
  )

  const template: PrintTemplate | undefined =
    available.find((entry) => entry.id === templateId) ?? available[0]

  const pages = template ? paginate(items, template, startPosition) : []
  const labelCount = items.reduce((total, item) => total + Math.max(1, item.copies), 0)
  const perPage = template ? (template.mode === 'single' ? 1 : template.columns * template.rows) : 1

  const persist = (next: PrintQueueItem[]) => {
    setItems(next)
    updateQueue.mutate(
      next.map((item, index) => ({ id: item.id, copies: item.copies, position: index })),
      {
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
      },
    )
  }

  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length) return
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    persist(next)
  }

  const print = () => {
    if (!template) return
    createJob.mutate(
      {
        printer_id: printerId || null,
        template_id: template.id,
        start_position: startPosition,
        items: items.map((item) => ({ queue_item_id: item.id, copies: item.copies })),
      },
      {
        onSuccess: (job) => {
          setConfirmOpen(false)
          setPrintedJobId(job.id)
          toast.success(t('printing.jobRegistered'))
          // El PrintJob queda registrado ANTES de abrir el dialogo del sistema.
          window.setTimeout(() => window.print(), 50)
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
      },
    )
  }

  if (queue.isPending || templates.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (queue.isError) return <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
  if (templates.isError)
    return <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />

  return (
    <div className="flex flex-col gap-6 pb-24">
      <div className="estampa-no-print flex flex-col gap-6">
        <PageHeader title={t('printing.title')} description={t('printing.subtitle')} />

        {items.length === 0 ? (
          <EmptyState
            icon={Stack}
            title={t('printing.emptyTitle')}
            description={t('printing.emptyBody')}
            action={
              <Button asChild>
                <Link to="/documents">{t('printing.emptyCta')}</Link>
              </Button>
            }
          />
        ) : (
          <div className="grid gap-6 lg:grid-cols-2">
            <section aria-label={t('printing.queueSection')} className="flex flex-col gap-3">
              <h2 className="text-h2 font-semibold">{t('printing.queueSection')}</h2>
              <QueueList
                items={items}
                onMove={move}
                onCopies={(id, copies) =>
                  persist(items.map((item) => (item.id === id ? { ...item, copies } : item)))
                }
                onRemove={setPendingRemoval}
              />
            </section>

            <section aria-label={t('printing.settings')} className="flex flex-col gap-4">
              <h2 className="text-h2 font-semibold">{t('printing.settings')}</h2>

              <FormField>
                <FormLabel>{t('printing.printer')}</FormLabel>
                <Select
                  value={printerId}
                  onValueChange={(value) => {
                    setPrinterId(value)
                    try {
                      window.localStorage.setItem(PRINTER_KEY, value)
                    } catch {
                      /* preferencia no persistible */
                    }
                  }}
                >
                  <SelectTrigger aria-label={t('printing.printer')}>
                    <SelectValue placeholder={t('printing.systemPrinter')} />
                  </SelectTrigger>
                  <SelectContent>
                    {(printers.data?.items ?? []).map((printer) => (
                      <SelectItem key={printer.id} value={printer.id}>
                        {printer.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">{t('printing.mode')}</legend>
                <RadioGroup value={mode} onValueChange={(value) => setMode(value as 'single' | 'grid')}>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="single" id="mode-single" />
                    <FieldLabel htmlFor="mode-single">{t('printing.modeSingle')}</FieldLabel>
                  </div>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="grid" id="mode-grid" />
                    <FieldLabel htmlFor="mode-grid">{t('printing.modeGrid')}</FieldLabel>
                  </div>
                </RadioGroup>
              </fieldset>

              <FormField>
                <FormLabel>{t('printing.template')}</FormLabel>
                <Select
                  value={template?.id ?? ''}
                  onValueChange={(value) => {
                    setTemplateId(value)
                    try {
                      window.localStorage.setItem(TEMPLATE_KEY, value)
                    } catch {
                      /* preferencia no persistible */
                    }
                  }}
                >
                  <SelectTrigger aria-label={t('printing.template')}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {available.map((entry) => (
                      <SelectItem key={entry.id} value={entry.id}>
                        {pick(entry, 'label')}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>

              {mode === 'grid' ? (
                <FormField>
                  <StartPositionField
                    value={startPosition}
                    onChange={setStartPosition}
                    max={perPage}
                  />
                </FormField>
              ) : null}
            </section>
          </div>
        )}
      </div>

      {template && items.length > 0 ? (
        <section aria-label={t('printing.preview')} className="flex flex-col gap-3">
          <h2 className="estampa-no-print text-h2 font-semibold">{t('printing.preview')}</h2>
          <div className="overflow-x-auto">
            <PrintSheet
              items={items}
              template={template}
              startPosition={startPosition}
              tenantName={user?.sites.find((site) => site.id === user.site_id)?.name ?? null}
            />
          </div>
        </section>
      ) : null}

      {items.length > 0 && template ? (
        <div className="estampa-no-print fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card px-4 py-3">
          <div className="mx-auto flex max-w-[var(--content-max)] flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              {t('printing.summary', {
                labels: formatNumber(labelCount, locale),
                pages: formatNumber(pages.length, locale),
              })}
            </p>
            <Button onClick={() => setConfirmOpen(true)} disabled={createJob.isPending}>
              <Printer size={20} aria-hidden="true" />
              {t('printing.print')}
            </Button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t('printing.confirmTitle')}
        description={t('printing.confirmBody', {
          labels: formatNumber(labelCount, locale),
          pages: formatNumber(pages.length, locale),
        })}
        objectName={template ? pick(template, 'label') : ''}
        confirmLabel={t('printing.print')}
        destructive={false}
        disabled={createJob.isPending}
        onConfirm={print}
      />

      <ConfirmDialog
        open={Boolean(pendingRemoval)}
        onOpenChange={(open) => !open && setPendingRemoval(null)}
        title={t('printing.removeTitle')}
        description={t('printing.removeBody')}
        objectName={pendingRemoval?.original_name ?? ''}
        confirmLabel={t('common.remove')}
        onConfirm={() => {
          if (!pendingRemoval) return
          removeItem.mutate(pendingRemoval.id, {
            onSuccess: () => {
              toast.success(t('printing.removed'))
              setPendingRemoval(null)
            },
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
          })
        }}
      />

      {/* Tras imprimir: "¿Se imprimio bien?" (print-queue.md). */}
      <AlertDialog open={Boolean(printedJobId)} onOpenChange={() => undefined}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('printing.didItPrintTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('printing.didItPrintBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                if (!printedJobId) return
                confirmJob.mutate(
                  { jobId: printedJobId, ok: false },
                  {
                    onSuccess: () => toast.error(t('printing.markedFailed')),
                  },
                )
                setPrintedJobId(null)
              }}
            >
              {t('printing.printFailed')}
            </AlertDialogCancel>
            <AlertDialogAction
              variant="default"
              onClick={() => {
                if (!printedJobId) return
                confirmJob.mutate(
                  { jobId: printedJobId, ok: true },
                  {
                    onSuccess: () => {
                      toast.success(t('printing.queueCleared'))
                      setItems([])
                    },
                  },
                )
                setPrintedJobId(null)
              }}
            >
              {t('printing.printOk')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
