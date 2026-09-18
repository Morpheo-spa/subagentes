import { type RowSelectionState } from '@tanstack/react-table'
import { DownloadSimple, FileDashed, Printer, Prohibit, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { EmptyState } from '@/components/common/empty-state'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { ApiError, buildUrl } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import type { DocumentListParams } from '@/lib/types'
import { DocumentSheet } from './document-sheet'
import { DocumentsCards } from './documents-cards'
import { DocumentsFilters } from './documents-filters'
import { DocumentsTable } from './documents-table'
import { useDocuments, useQueueForPrint, useWithdrawDocuments } from './documents-queries'

const INITIAL_PARAMS: DocumentListParams = {
  page: 1,
  page_size: 25,
  sort: 'uploaded_at',
  order: 'desc',
}

export default function DocumentsPage() {
  const { t } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()
  const [params, setParams] = useState<DocumentListParams>(INITIAL_PARAMS)
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [reason, setReason] = useState('')

  const openId = searchParams.get('document')
  const list = useDocuments(params)
  const queue = useQueueForPrint()
  const withdraw = useWithdrawDocuments()

  const selectedIds = Object.keys(selection).filter((id) => selection[id])
  const documents = list.data?.items ?? []

  const open = (documentId: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('document', documentId)
    setSearchParams(next)
  }

  const closeSheet = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('document')
    setSearchParams(next)
  }

  const addToQueue = (ids: string[]) =>
    queue.mutate(
      ids.map((id) => ({ document_id: id, copies: 1 })),
      {
        onSuccess: () => {
          toast.success(t('printing.addedToQueue', { count: ids.length }))
          setSelection({})
        },
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
      },
    )

  const exportCsv = () => {
    // Descarga directa: la API responde text/csv con el filtro aplicado.
    const url = buildUrl('/documents/export', { ...params, ids: selectedIds.join(',') })
    window.open(url, '_blank', 'noopener')
    toast.success(t('documents.exportStarted'))
  }

  return (
    <div className="flex flex-col gap-6 pb-24">
      <PageHeader title={t('documents.title')} description={t('documents.subtitle')} />

      <DocumentsFilters
        params={params}
        onChange={(patch) => setParams((current) => ({ ...current, ...patch }))}
        onReset={() => setParams(INITIAL_PARAMS)}
      />

      {list.isPending ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : documents.length === 0 ? (
        <EmptyState
          icon={FileDashed}
          title={t('documents.emptyTitle')}
          description={t('documents.emptyBody')}
          action={
            <Button asChild>
              <Link to="/upload">{t('documents.emptyCta')}</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="hidden md:block">
            <DocumentsTable
              documents={documents}
              selection={selection}
              onSelectionChange={setSelection}
              onOpen={(document) => open(document.id)}
              onPrint={(document) => addToQueue([document.id])}
              onWithdraw={(document) => {
                setSelection({ [document.id]: true })
                setWithdrawOpen(true)
              }}
              params={params}
              onSort={(field) =>
                setParams((current) => ({
                  ...current,
                  sort: field,
                  order: current.sort === field && current.order === 'asc' ? 'desc' : 'asc',
                }))
              }
            />
          </div>
          <div className="md:hidden">
            <DocumentsCards
              documents={documents}
              onOpen={(document) => open(document.id)}
              onPrint={(document) => addToQueue([document.id])}
            />
          </div>

          <Pagination
            page={params.page}
            pageSize={params.page_size}
            total={list.data?.total ?? 0}
            onPageChange={(page) => setParams((current) => ({ ...current, page }))}
            onPageSizeChange={(size) =>
              setParams((current) => ({ ...current, page_size: size, page: 1 }))
            }
          />
        </>
      )}

      {/* Action bar flotante para la seleccion multiple (documents.md). */}
      {selectedIds.length > 0 ? (
        <div
          role="region"
          aria-label={t('documents.bulkActions')}
          className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card px-4 py-3"
        >
          <div className="mx-auto flex max-w-[var(--content-max)] flex-wrap items-center gap-2">
            <p className="text-sm font-medium">
              {t('documents.selectedCount', { count: selectedIds.length })}
            </p>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" onClick={() => addToQueue(selectedIds)} disabled={queue.isPending}>
                <Printer size={16} aria-hidden="true" />
                {t('documents.addToQueue')}
              </Button>
              <Button size="sm" variant="outline" onClick={exportCsv}>
                <DownloadSimple size={16} aria-hidden="true" />
                {t('documents.exportCsv')}
              </Button>
              <Button size="sm" variant="destructive" onClick={() => setWithdrawOpen(true)}>
                <Prohibit size={16} aria-hidden="true" />
                {t('documents.withdraw')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('documents.clearSelection')}
                onClick={() => setSelection({})}
              >
                <X size={16} aria-hidden="true" />
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={withdrawOpen}
        onOpenChange={setWithdrawOpen}
        title={t('documents.withdrawTitle')}
        description={t('documents.withdrawBodyBulk', { count: selectedIds.length })}
        objectName={
          selectedIds.length === 1
            ? (documents.find((document) => document.id === selectedIds[0])?.original_name ?? '')
            : t('documents.nSelected', { count: selectedIds.length })
        }
        confirmLabel={t('documents.withdraw')}
        disabled={!reason.trim() || withdraw.isPending}
        extra={
          <div className="flex flex-col gap-2">
            <Label htmlFor="bulk-withdraw-reason">{t('documents.withdrawReason')}</Label>
            <Input
              id="bulk-withdraw-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
        }
        onConfirm={() =>
          withdraw.mutate(
            { ids: selectedIds, reason },
            {
              onSuccess: () => {
                toast.success(t('documents.withdrawn'))
                setWithdrawOpen(false)
                setSelection({})
                setReason('')
              },
              onError: (error) =>
                toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
            },
          )
        }
      />

      <DocumentSheet documentId={openId} onClose={closeSheet} />
    </div>
  )
}
