import { useMutation } from '@tanstack/react-query'
import { Printer, SlidersHorizontal } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { useBlocker, useNavigate } from 'react-router-dom'
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
import { Progress } from '@/components/ui/progress'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { toast } from '@/components/ui/sonner'
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError, request } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import * as routes from '@/lib/routes'
import type { DecaData, DocumentRead } from '@/lib/types'
import { DecaForm } from '@/features/deca/deca-form'
import { useDecaFields } from '@/features/deca/deca-queries'
import type { DecaValues } from '@/features/deca/deca-validation'
import { useAddToQueue } from '@/features/printing/printing-queries'
import { UploadDropZone } from './upload-drop-zone'
import { UploadRow } from './upload-row'
import { useUploadBatch } from './use-upload-batch'

export default function UploadPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [applied, setApplied] = useState(0)

  const batch = useUploadBatch()
  const catalog = useDecaFields()
  const queuePrint = useAddToQueue()

  // upload.md: salir con subidas en curso -> AlertDialog.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      batch.inFlight && currentLocation.pathname !== nextLocation.pathname,
  )

  useEffect(() => {
    if (!batch.inFlight) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [batch.inFlight])

  /**
   * No hay endpoint de lote para metadatos (`PATCH /documents/batch/deca` no
   * existe): se aplica documento a documento con `PATCH /documents/{id}/deca`,
   * con su progreso y sin que un fallo tumbe al resto.
   */
  const applyMetadata = useMutation({
    mutationFn: async (values: DecaValues) => {
      const targets = batch.readyItems.map((item) => item.document).filter(Boolean)
      const failures: string[] = []
      setApplied(0)
      for (const [index, document] of targets.entries()) {
        try {
          await request<DocumentRead>(routes.documentPatchDeca({ documentId: document!.id }), {
            body: { deca: values as DecaData },
          })
        } catch {
          failures.push(document!.original_filename)
        }
        setApplied(index + 1)
      }
      return { total: targets.length, failures }
    },
    onSuccess: ({ total, failures }) => {
      if (failures.length > 0) {
        toast.error(t('upload.metadataPartial', { done: total - failures.length, total }))
        return
      }
      toast.success(t('upload.metadataApplied', { count: total }))
      setMetadataOpen(false)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  // Solo lo que es un DeCA valido entra en la cola de etiquetas.
  const printableIds = batch.printableItems
    .map((item) => item.document?.id)
    .filter((id): id is string => Boolean(id))

  const sendToPrint = (documentIds: string[]) =>
    queuePrint.mutate(
      { documentIds },
      {
        onSuccess: () => {
          toast.success(t('printing.addedToQueue', { count: documentIds.length }))
          navigate('/printing')
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
      },
    )

  return (
    <div className="flex flex-col gap-6 pb-24">
      <PageHeader
        title={t('upload.title')}
        description={t('upload.subtitle')}
        actions={
          <Button
            variant="outline"
            disabled={batch.readyItems.length === 0}
            onClick={() => setMetadataOpen(true)}
          >
            <SlidersHorizontal size={20} aria-hidden="true" />
            {t('upload.batchMetadata')}
          </Button>
        }
      />

      <UploadDropZone onFiles={batch.addFiles} maxBytes={batch.maxBytes} />

      {/* MASTER §10 y upload.md: un solo anuncio con el recuento, no un toast por
          fichero. Solo para lectores de pantalla: en pantalla el recuento ya lo
          da la barra inferior, y no se dice dos veces. */}
      <p aria-live="polite" role="status" className="sr-only">
        {batch.counts.total > 0
          ? t('upload.readyCount', { ready: batch.counts.ready, total: batch.counts.total })
          : ''}
      </p>

      {/* Sin estado vacio: la zona de drop ya dice que hacer. Un segundo bloque
          repitiendo "arrastra tus PDFs" es ruido. */}
      {batch.items.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('upload.columns.file')}</TableHead>
              <TableHead>{t('upload.columns.status')}</TableHead>
              <TableHead>{t('upload.columns.qr')}</TableHead>
              <TableHead>{t('upload.columns.guid')}</TableHead>
              <TableHead>{t('upload.columns.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {batch.items.map((item) => (
              <UploadRow
                key={item.id}
                item={item}
                onRetry={batch.retry}
                onRemove={batch.remove}
                onPrint={(entry) => entry.document && sendToPrint([entry.document.id])}
              />
            ))}
          </TableBody>
        </Table>
      ) : null}

      {/* Barra fija inferior (upload.md). */}
      {batch.items.length > 0 ? (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card px-4 py-3">
          <div className="mx-auto flex max-w-[var(--content-max)] flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              {t('upload.summary', {
                total: batch.counts.total,
                ready: batch.counts.ready,
                errors: batch.counts.errors,
              })}
            </p>
            <Button
              disabled={printableIds.length === 0 || queuePrint.isPending}
              onClick={() => sendToPrint(printableIds)}
            >
              <Printer size={20} aria-hidden="true" />
              {t('upload.sendToPrint', { count: printableIds.length })}
            </Button>
          </div>
        </div>
      ) : null}

      <Sheet open={metadataOpen} onOpenChange={setMetadataOpen}>
        <SheetContent closeLabel={t('common.close')} className="max-w-2xl">
          <SheetHeader>
            <SheetTitle>{t('upload.batchMetadata')}</SheetTitle>
            <SheetDescription>
              {t('upload.batchMetadataHelp', { count: batch.readyItems.length })}
            </SheetDescription>
          </SheetHeader>
          {applyMetadata.isPending ? (
            <Progress
              value={Math.round((applied / Math.max(1, batch.readyItems.length)) * 100)}
              aria-label={t('upload.metadataProgress', {
                done: applied,
                total: batch.readyItems.length,
              })}
            />
          ) : null}
          {catalog.data ? (
            <DecaForm
              fields={catalog.data.fields}
              submitLabel={t('upload.applyMetadata')}
              submitting={applyMetadata.isPending}
              onSubmit={async (values) => {
                await applyMetadata.mutateAsync(values).catch(() => undefined)
              }}
            />
          ) : null}
        </SheetContent>
      </Sheet>

      <AlertDialog
        open={blocker.state === 'blocked'}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.()
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('upload.leaveTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('upload.leaveBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>
              {t('upload.stay')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.proceed?.()}>
              {t('upload.leave')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
