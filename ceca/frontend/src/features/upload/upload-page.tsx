import { useMutation, useQuery } from '@tanstack/react-query'
import { FileArrowUp, Printer, SlidersHorizontal } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { useBlocker, useNavigate } from 'react-router-dom'
import { EmptyState } from '@/components/common/empty-state'
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
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { toast } from '@/components/ui/sonner'
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api, ApiError } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { DecaForm } from '@/features/deca/deca-form'
import { useDecaFields } from '@/features/deca/deca-queries'
import type { DecaValues } from '@/features/deca/deca-validation'
import { UploadDropZone } from './upload-drop-zone'
import { UploadRow } from './upload-row'
import { useUploadBatch, type ClientLimits } from './use-upload-batch'

export default function UploadPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [metadataOpen, setMetadataOpen] = useState(false)

  const limits = useQuery({
    queryKey: ['documents', 'limits'],
    queryFn: () => api.get<ClientLimits>('/documents/limits'),
    staleTime: 10 * 60_000,
  })

  const batch = useUploadBatch(limits.data)
  const catalog = useDecaFields()

  // upload.md: salir con subidas en curso -> AlertDialog.
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
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

  const queuePrint = useMutation({
    mutationFn: (documentIds: string[]) =>
      api.post('/printing/queue', {
        items: documentIds.map((documentId) => ({ document_id: documentId, copies: 1 })),
      }),
    onSuccess: (_result, documentIds) => {
      toast.success(t('printing.addedToQueue', { count: documentIds.length }))
      navigate('/printing')
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  const applyMetadata = useMutation({
    mutationFn: (values: DecaValues) =>
      api.patch('/documents/batch/deca', {
        document_ids: batch.readyItems.map((item) => item.document?.id).filter(Boolean),
        values,
      }),
    onSuccess: () => {
      toast.success(t('upload.metadataApplied', { count: batch.readyItems.length }))
      setMetadataOpen(false)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  const readyIds = batch.readyItems.map((item) => item.document?.id).filter((id): id is string => Boolean(id))

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

      {/* MASTER §10 y upload.md: un solo anuncio con el recuento, no un toast por fichero. */}
      <p aria-live="polite" role="status" className="text-sm text-muted-foreground">
        {batch.counts.total > 0
          ? t('upload.readyCount', { ready: batch.counts.ready, total: batch.counts.total })
          : ''}
      </p>

      {batch.items.length === 0 ? (
        <EmptyState
          icon={FileArrowUp}
          title={t('upload.emptyTitle')}
          description={t('upload.emptyBody')}
        />
      ) : (
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
                onUploadAnyway={batch.uploadAnyway}
                onUseExisting={batch.useExisting}
                onPrint={(entry) => entry.document && queuePrint.mutate([entry.document.id])}
              />
            ))}
          </TableBody>
        </Table>
      )}

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
              disabled={readyIds.length === 0 || queuePrint.isPending}
              onClick={() => queuePrint.mutate(readyIds)}
            >
              <Printer size={20} aria-hidden="true" />
              {t('upload.sendToPrint', { count: readyIds.length })}
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
