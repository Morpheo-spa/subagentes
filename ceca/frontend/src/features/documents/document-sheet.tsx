import {
  ClockCounterClockwise,
  DotsThree,
  Printer,
  Prohibit,
  QrCode,
} from '@phosphor-icons/react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { CopyButton } from '@/components/common/copy-button'
import { ComplianceBadge, StatusBadge } from '@/components/common/status-badge'
import { ErrorState } from '@/components/common/error-state'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError } from '@/lib/api'
import { formatBytes, formatDate, formatDateTime, formatNumber } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import { useAddToQueue } from '@/features/printing/printing-queries'
import {
  useDocument,
  useDocumentHistory,
  useRevokeShare,
  useWithdrawDocuments,
} from './documents-queries'

function Meta({ label, children }: { label: string; children: ReactNode }) {
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
  const history = useDocumentHistory(documentId)
  const queue = useAddToQueue()
  const withdraw = useWithdrawDocuments()
  const revoke = useRevokeShare()
  const [copies, setCopies] = useState(1)
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [reason, setReason] = useState('')

  const document = detail.data
  const publicUrl = document?.public_url ?? null
  const revisions = history.data?.revisions ?? []
  const prints = history.data?.prints ?? []

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
              <SheetTitle>{document.original_filename}</SheetTitle>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={document.status} expiresAt={document.expires_at} />
                <ComplianceBadge status={document.compliance_status} />
              </div>
            </SheetHeader>

            {/* Retirada: el aviso se conserva entero (fecha y motivo), en linea
                y sin caja. */}
            {document.withdrawn_at ? (
              <p className="flex items-start gap-1.5 text-sm text-destructive-text">
                <Prohibit size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                {t('documents.withdrawnOn', {
                  date: formatDate(document.withdrawn_at, locale),
                  reason: document.withdrawn_reason ?? t('documents.noReason'),
                })}
              </p>
            ) : null}

            <div className="flex flex-col items-start gap-3">
              <QrImage
                documentId={document.id}
                documentName={document.original_filename}
                size={200}
              />
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
                  <Meta label={t('documents.size')}>{formatBytes(document.byte_size, locale)}</Meta>
                  <Meta label={t('documents.columns.uploadedAt')}>
                    {formatDateTime(document.created_at, locale)}
                  </Meta>
                  <Meta label={t('documents.origin')}>{t(`origin.${document.origin}`)}</Meta>
                  <Meta label={t('documents.columns.expiresAt')}>
                    {formatDate(document.expires_at, locale)}
                  </Meta>
                  <Meta label={t('documents.columns.prints')}>
                    {formatNumber(document.print_count, locale)}
                  </Meta>
                  {/* Fuera: la revision vigente ya la cuenta la pestana
                      "Revisiones", y un SHA-256 cortado a 16 caracteres no se
                      puede verificar ni copiar: era relleno. */}
                </dl>
                <Button variant="outline" className="mt-4" asChild>
                  <Link to={`/deca/${document.id}`}>{t('documents.editDeca')}</Link>
                </Button>
              </TabsContent>

              <TabsContent value="revisions">
                <ul className="flex flex-col gap-4">
                  {revisions.map((revision) => (
                    <li key={revision.id} className="text-sm">
                      <p className="font-medium">
                        {t('documents.revisionN', { n: revision.revision })}
                        {revision.is_current ? '' : ` · ${t('documents.superseded')}`}
                      </p>
                      <p className="text-meta text-muted-foreground">
                        {formatDateTime(revision.created_at, locale)}
                      </p>
                      {revision.change_reason ? (
                        <p className="mt-1">{revision.change_reason}</p>
                      ) : null}
                    </li>
                  ))}
                  {revisions.length === 0 ? (
                    <li className="text-sm text-muted-foreground">{t('documents.noRevisions')}</li>
                  ) : null}
                </ul>
              </TabsContent>

              <TabsContent value="history">
                <ul className="flex flex-col gap-2">
                  {prints.map((entry) => (
                    <li key={entry.print_job_id} className="flex items-start gap-2 text-sm">
                      <ClockCounterClockwise
                        size={16}
                        aria-hidden="true"
                        className="mt-1 shrink-0 text-muted-foreground"
                      />
                      <span>
                        <span className="font-medium">
                          {t('documents.printedCopies', { count: entry.copies })}
                        </span>{' '}
                        <span className="text-muted-foreground">
                          {formatDateTime(entry.printed_at, locale)}
                        </span>
                      </span>
                    </li>
                  ))}
                  {prints.length === 0 ? (
                    <li className="text-sm text-muted-foreground">{t('documents.noEvents')}</li>
                  ) : null}
                </ul>
              </TabsContent>
            </Tabs>

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
              {/* Un escaneo no entra en la cola de etiquetas: no es un DeCA. */}
              {document.is_valid_deca ? (
                <Button
                  onClick={() =>
                    queue.mutate(
                      { documentIds: [document.id], copies },
                      {
                        onSuccess: () =>
                          toast.success(t('printing.addedWithCopies', { count: copies })),
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
              ) : (
                <p className="text-sm text-destructive-text">{t('documents.notPrintable')}</p>
              )}

              {/* Una sola accion primaria en el panel. Revocar y retirar son
                  raras y destructivas: viven en el menu, como en la tabla. */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t('documents.rowActions', {
                      name: document.original_filename,
                    })}
                  >
                    <DotsThree size={20} aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setRevokeOpen(true)}>
                    <QrCode size={16} aria-hidden="true" />
                    {t('documents.revokeToken')}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => setWithdrawOpen(true)}
                  >
                    <Prohibit size={16} aria-hidden="true" />
                    {t('documents.withdraw')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <ConfirmDialog
              open={withdrawOpen}
              onOpenChange={setWithdrawOpen}
              title={t('documents.withdrawTitle')}
              description={t('documents.withdrawBody')}
              objectName={document.original_filename}
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
                    onSuccess: ({ failed }) => {
                      if (failed.length > 0) {
                        toast.error(t('errors.unexpected'))
                        return
                      }
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
              objectName={document.original_filename}
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
