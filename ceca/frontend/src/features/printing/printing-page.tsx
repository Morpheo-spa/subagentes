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
import { FormDescription, FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label as FieldLabel } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatNumber } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { LabelTemplateRead, PrintLayout, QueueItemRead } from '@/lib/types'
import { paginate, PrintSheet, slotsPerPage } from './print-sheet'
import { QueueList } from './queue-list'
import {
  fetchJobRender,
  useConfirmPrintJob,
  useCreatePrintJob,
  usePrintQueue,
  usePrintTemplates,
  useRemoveFromQueue,
  useReorderQueue,
} from './printing-queries'

/**
 * Solo el NOMBRE que el usuario teclea, que es lo que el backend guarda en
 * `PrintJob.printer_name` como etiqueta del trabajo. La impresora de verdad la
 * elige el dialogo nativo: el navegador no puede enumerar impresoras, y el
 * backend no tiene (ni puede tener) un catalogo de ellas.
 */
const PRINTER_NAME_KEY = 'estampa.printerName'
const TEMPLATE_KEY = 'estampa.template'

function TextField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  hint?: string
}) {
  const control = useFormControlProps()
  return (
    <>
      <FormLabel>{label}</FormLabel>
      <Input {...control} value={value} onChange={(event) => onChange(event.target.value)} />
      {hint ? <FormDescription>{hint}</FormDescription> : null}
    </>
  )
}

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
  const { site } = useAuth()
  const queue = usePrintQueue()
  const templates = usePrintTemplates()
  const reorder = useReorderQueue()
  const removeItem = useRemoveFromQueue()
  const createJob = useCreatePrintJob()
  const confirmJob = useConfirmPrintJob()

  const [items, setItems] = useState<QueueItemRead[]>([])
  const [layout, setLayout] = useState<PrintLayout>('sheet')
  const [templateCode, setTemplateCode] = useState('')
  const [printerName, setPrinterName] = useState('')
  const [startPosition, setStartPosition] = useState(1)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingRemoval, setPendingRemoval] = useState<QueueItemRead | null>(null)
  const [printedJobId, setPrintedJobId] = useState<string | null>(null)

  useEffect(() => {
    if (queue.data) setItems(queue.data.items)
  }, [queue.data])

  // Recordar nombre de trabajo y plantilla (print-queue.md).
  useEffect(() => {
    try {
      const storedPrinter = window.localStorage.getItem(PRINTER_NAME_KEY)
      const storedTemplate = window.localStorage.getItem(TEMPLATE_KEY)
      if (storedPrinter) setPrinterName(storedPrinter)
      if (storedTemplate) setTemplateCode(storedTemplate)
    } catch {
      /* preferencia no persistible */
    }
  }, [])

  const available = useMemo(
    () => (templates.data?.items ?? []).filter((entry) => (entry.layout ?? 'sheet') === layout),
    [templates.data, layout],
  )

  const template: LabelTemplateRead | undefined =
    available.find((entry) => entry.code === templateCode) ?? available[0]

  const pages = template ? paginate(items, template, startPosition) : []
  const labelCount = items.reduce((total, item) => total + Math.max(1, item.copies), 0)
  const perPage = template ? slotsPerPage(template) : 1

  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length) return
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    setItems(next)
    reorder.mutate(
      next.map((item) => item.id),
      {
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
      },
    )
  }

  const print = () => {
    if (!template) return
    createJob.mutate(
      {
        template_code: template.code,
        printer_name: printerName.trim() || null,
        start_position: startPosition,
        item_ids: items.map((item) => item.id),
      },
      {
        onSuccess: async (job) => {
          setConfirmOpen(false)
          setPrintedJobId(job.id)
          toast.success(t('printing.jobRegistered'))
          // El PrintJob queda registrado ANTES de abrir el dialogo del sistema.
          // El folio lo compone el backend; la impresora la elige ese dialogo.
          try {
            const blob = await fetchJobRender(job.id)
            const url = URL.createObjectURL(blob)
            window.open(url, '_blank', 'noopener')
          } catch (error) {
            toast.error(error instanceof ApiError ? error.message : t('errors.unexpected'))
          }
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
  if (templates.isError) {
    return <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
  }

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
              <QueueList items={items} onMove={move} onRemove={setPendingRemoval} />
            </section>

            <section aria-label={t('printing.settings')} className="flex flex-col gap-4">
              <h2 className="text-h2 font-semibold">{t('printing.settings')}</h2>

              <FormField>
                <TextField
                  label={t('printing.jobName')}
                  value={printerName}
                  hint={t('printing.jobNameHelp')}
                  onChange={(value) => {
                    setPrinterName(value)
                    try {
                      window.localStorage.setItem(PRINTER_NAME_KEY, value)
                    } catch {
                      /* preferencia no persistible */
                    }
                  }}
                />
              </FormField>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">{t('printing.mode')}</legend>
                <RadioGroup
                  value={layout}
                  onValueChange={(value) => setLayout(value as PrintLayout)}
                >
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="single" id="mode-single" />
                    <FieldLabel htmlFor="mode-single">{t('printing.modeSingle')}</FieldLabel>
                  </div>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="sheet" id="mode-sheet" />
                    <FieldLabel htmlFor="mode-sheet">{t('printing.modeGrid')}</FieldLabel>
                  </div>
                </RadioGroup>
              </fieldset>

              <FormField>
                <FormLabel>{t('printing.template')}</FormLabel>
                <Select
                  value={template?.code ?? ''}
                  onValueChange={(value) => {
                    setTemplateCode(value)
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
                      <SelectItem key={entry.code} value={entry.code}>
                        {pick(entry, 'name') || entry.code}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>

              {perPage > 1 ? (
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
              siteName={site?.name ?? null}
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
        objectName={template ? (pick(template, 'name') || template.code) : ''}
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
        objectName={pendingRemoval?.document?.original_filename ?? ''}
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
                  { jobId: printedJobId, success: false },
                  { onSuccess: () => toast.error(t('printing.markedFailed')) },
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
                  { jobId: printedJobId, success: true },
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
