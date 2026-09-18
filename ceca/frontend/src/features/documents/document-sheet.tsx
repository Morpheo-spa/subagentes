import { ClockCounterClockwise, Printer, Prohibit, QrCode } from '@phosphor-icons/react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { CopyButton } from '@/components/common/copy-button'
import { ComplianceBadge, StatusBadge } from '@/components/common/status-badge'
import { ErrorState } from '@/components/common/error-state'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError } from '@/lib/api'
import { formatBytes, formatDate, formatDateTime, formatNumber } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import { useDocument, useQueueForPrint, useRevokeToken, useWithdrawDocuments } from './documents-queries'

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-meta text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  )
}

export function DocumentSheet({
  documentId,
  onClose,
}: {
  documentId: string | null
  onClose: () => void
}) {
  const { t, locale } = useI18n()
  const detail = useDocument(documentId)
  const queue = useQueueForPrint()
  const withdraw = useWithdrawDocuments()
  const revoke = useRevokeToken()
  const [copies, setCopies] = useState(1)
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [reason, setReason] = useState('')

  const document = detail.data
  const publicUrl = document?.public_url ?? null

  return (
    <Sheet open={Boolean(documentId)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent closeLabel={t('common.close')} className="max-w-xl">
        {detail.isPending ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-7 w-64" />
            <Skeleton className="h-52 w-52" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : detail.isError ? (
          <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
        ) : document ? (
          <>
            <SheetHeader>
              <SheetTitle>{document.original_name}</SheetTitle>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={document.status} expiresAt={document.expires_at} />
                <ComplianceBadge status={document.compliance_status} />
              </div>
            </SheetHeader>

            {document.withdrawn_at ? (
              <p className="rounded-md border border-destructive bg-destructive-surface p-3 text-sm text-destructive-text">
                {t('documents.withdrawnOn', {
                  date: formatDate(document.withdrawn_at, locale),
                  reason: document.withdrawn_reason ?? t('documents.noReason'),
                })}
              </p>
            ) : null}

            <div className="flex flex-col items-start gap-3">
              <QrImage src={document.qr_url} documentName={document.original_name} size={200} />
              {publicUrl ? (
                <div className="flex w-full items-center gap-2">
                  <code className="estampa-mono min-w-0 flex-1 truncate text-meta text-muted-foreground">
                    {publicUrl}
                  </code>
                  <CopyButton value={publicUrl} label={t('documents.copyPublicUrl')} />
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{t('documents.noPublicUrl')}</p>
              )}
            </div>

            <Separator />

            <Tabs defaultValue="metadata">
              <TabsList>
                <TabsTrigger value="metadata">{t('documents.tabs.metadata')}</TabsTrigger>
                <TabsTrigger value="revisions">{t('documents.tabs.revisions')}</TabsTrigger>
                <TabsTrigger value="history">{t('documents.tabs.history')}</TabsTrigger>
              </TabsList>

              <TabsContent value="metadata">
                <dl className="grid grid-cols-2 gap-3">
                  <Meta label={t('documents.columns.guid')}>
                    <Guid value={document.id} />
                  </Meta>
                  <Meta label={t('documents.size')}>{formatBytes(document.size_bytes, locale)}</Meta>
                  <Meta label={t('documents.columns.uploadedAt')}>
                    {formatDateTime(document.uploaded_at, locale)}
                  </Meta>
                  <Meta label={t('documents.uploadedBy')}>{document.uploaded_by}</Meta>
                  <Meta label={t('documents.columns.expiresAt')}>
                    {formatDate(document.expires_at, locale)}
                  </Meta>
                  <Meta label={t('documents.retention')}>
                    {t('documents.retentionDays', {
                      days: formatNumber(document.retention_days, locale),
                    })}
                  </Meta>
                  <Meta label={t('documents.columns.prints')}>
                    {formatNumber(document.print_count, locale)}
                  </Meta>
                  <Meta label={t('documents.sha256')}>
                    <code className="estampa-mono text-meta">{document.sha256.slice(0, 16)}…</code>
                  </Meta>
                </dl>
                <Button variant="outline" className="mt-4" asChild>
                  <Link to={`/deca/${document.id}`}>{t('documents.editDeca')}</Link>
                </Button>
              </TabsContent>

              <TabsContent value="revisions">
                <ul className="flex flex-col gap-2">
                  {document.revisions.map((revision) => (
                    <li
                      key={revision.id}
                      className="rounded-md border border-border p-3 text-sm"
                    >
                      <p className="font-medium">
                        {t('documents.revisionN', { n: revision.revision })}
                        {revision.superseded ? ` · ${t('documents.superseded')}` : ''}
                      </p>
                      <p className="text-meta text-muted-foreground">
                        {formatDateTime(revision.created_at, locale)}
                      </p>
                      {revision.change_reason ? (
                        <p className="mt-1">{revision.change_reason}</p>
                      ) : null}
                    </li>
                  ))}
                  {document.revisions.length === 0 ? (
                    <li className="text-sm text-muted-foreground">{t('documents.noRevisions')}</li>
                  ) : null}
                </ul>
              </TabsContent>

              <TabsContent value="history">
                <ul className="flex flex-col gap-2">
                  {document.events.map((event) => (
                    <li key={event.id} className="flex items-start gap-2 text-sm">
                      <ClockCounterClockwise
                        size={16}
                        aria-hidden="true"
                        className="mt-1 shrink-0 text-muted-foreground"
                      />
                      <span>
                        <span className="font-medium">{t(`documents.events.${event.kind}`)}</span>{' '}
                        <span className="text-muted-foreground">
                          {formatDateTime(event.at, locale)}
                          {event.actor ? ` · ${event.actor}` : ''}
                        </span>
                      </span>
                    </li>
                  ))}
                  {document.events.length === 0 ? (
                    <li className="text-sm text-muted-foreground">{t('documents.noEvents')}</li>
                  ) : null}
                </ul>
              </TabsContent>
            </Tabs>

            <Separator />

            {/* documents.md: reimprimir nunca imprime directo, va a la cola. */}
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="document-copies">{t('printing.copies')}</Label>
                <Input
                  id="document-copies"
                  type="number"
                  min={1}
                  max={99}
                  className="w-24"
                  value={copies}
                  onChange={(event) => setCopies(Math.max(1, Number(event.target.value) || 1))}
                />
              </div>
              <Button
                onClick={() =>
                  queue.mutate(
                    [{ document_id: document.id, copies }],
                    {
                      onSuccess: () => toast.success(t('printing.addedWithCopies', { count: copies })),
                      onError: (error) =>
                        toast.error(
                          error instanceof ApiError ? error.message : t('errors.unexpected'),
                        ),
                    },
                  )
                }
                disabled={queue.isPending || Boolean(document.withdrawn_at)}
              >
                <Printer size={20} aria-hidden="true" />
                {t('documents.addToQueue')}
              </Button>
              <Button variant="outline" onClick={() => setRevokeOpen(true)}>
                <QrCode size={20} aria-hidden="true" />
                {t('documents.revokeToken')}
              </Button>
              <Button variant="destructive" onClick={() => setWithdrawOpen(true)}>
                <Prohibit size={20} aria-hidden="true" />
                {t('documents.withdraw')}
              </Button>
            </div>

            <ConfirmDialog
              open={withdrawOpen}
              onOpenChange={setWithdrawOpen}
              title={t('documents.withdrawTitle')}
              description={t('documents.withdrawBody')}
              objectName={document.original_name}
              confirmLabel={t('documents.withdraw')}
              disabled={!reason.trim() || withdraw.isPending}
              extra={
                <div className="flex flex-col gap-2">
                  <Label htmlFor="withdraw-reason">{t('documents.withdrawReason')}</Label>
                  <Input
                    id="withdraw-reason"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </div>
              }
              onConfirm={() =>
                withdraw.mutate(
                  { ids: [document.id], reason },
                  {
                    onSuccess: () => {
                      toast.success(t('documents.withdrawn'))
                      setWithdrawOpen(false)
                      onClose()
                    },
                    onError: (error) =>
                      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
                  },
                )
              }
            />

            <ConfirmDialog
              open={revokeOpen}
              onOpenChange={setRevokeOpen}
              title={t('documents.revokeTitle')}
              description={t('documents.revokeBody')}
              objectName={document.original_name}
              confirmLabel={t('documents.revokeToken')}
              disabled={revoke.isPending}
              onConfirm={() =>
                revoke.mutate(document.id, {
                  onSuccess: () => {
                    toast.success(t('documents.revoked'))
                    setRevokeOpen(false)
                  },
                  onError: (error) =>
                    toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
                })
              }
            />
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
