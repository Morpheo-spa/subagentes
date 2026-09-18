import { ArrowClockwise, Eye, Printer, Prohibit, Trash, WarningCircle } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import { CopyButton } from '@/components/common/copy-button'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { StatusBadge } from '@/components/common/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { TableCell, TableRow } from '@/components/ui/table'
import { formatBytes, formatDate, truncateMiddle } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { BatchItem } from './use-upload-batch'

export function UploadRow({
  item,
  onRetry,
  onRemove,
  onUploadAnyway,
  onUseExisting,
  onPrint,
}: {
  item: BatchItem
  onRetry: (id: string) => void
  onRemove: (id: string) => void
  onUploadAnyway: (id: string) => void
  onUseExisting: (id: string) => void
  onPrint: (item: BatchItem) => void
}) {
  const { t, locale } = useI18n()
  const document = item.document

  return (
    <TableRow className="estampa-row-enter align-top">
      <TableCell className="max-w-56">
        <p className="font-medium" title={item.name}>
          {truncateMiddle(item.name)}
        </p>
        <p className="text-meta text-muted-foreground">{formatBytes(item.size, locale)}</p>

        {item.status === 'duplicate' && item.duplicateOf ? (
          <div className="mt-2 rounded-md border border-warning bg-warning-surface p-2 text-warning-text">
            <p className="flex items-start gap-1.5 text-sm">
              <WarningCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
              {t('upload.duplicateWarning', {
                date: formatDate(item.duplicateOf.uploaded_at, locale),
              })}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => onUseExisting(item.id)}>
                {t('upload.useExisting')}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onUploadAnyway(item.id)}>
                {t('upload.uploadAnyway')}
              </Button>
            </div>
          </div>
        ) : null}

        {/* docs/DECA.md §1: un escaneo no produce un DeCA valido. */}
        {document?.compliance_status === 'NOT_A_DECA' ? (
          <div className="mt-2 rounded-md border border-destructive bg-destructive-surface p-2 text-destructive-text">
            <p className="flex items-start gap-1.5 text-sm">
              <Prohibit size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
              {t('upload.notADecaWarning')}
            </p>
            <Button size="sm" variant="outline" className="mt-2" asChild>
              <Link to="/deca/new">{t('upload.generateInstead')}</Link>
            </Button>
          </div>
        ) : null}
      </TableCell>

      <TableCell className="min-w-44">
        {item.status === 'uploading' ? (
          <div className="flex flex-col gap-1">
            <Progress value={item.progress} aria-label={t('upload.progressLabel', { name: item.name })} />
            <span className="text-meta text-muted-foreground">
              {t('upload.uploadingPercent', { percent: item.progress })}
            </span>
          </div>
        ) : item.status === 'rejected' || item.status === 'error' ? (
          <div className="flex flex-col gap-1">
            <Badge variant="destructive">
              <WarningCircle size={14} aria-hidden="true" />
              {t('status.error')}
            </Badge>
            <span className="text-meta text-destructive-text">
              {item.errorMessage ?? t(`upload.errorCodes.${item.errorCode ?? 'UNKNOWN_ERROR'}`)}
            </span>
            {item.errorCode ? (
              <span className="estampa-mono text-meta text-muted-foreground">{item.errorCode}</span>
            ) : null}
          </div>
        ) : item.status === 'duplicate' ? (
          <Badge variant="warning">
            <WarningCircle size={14} aria-hidden="true" />
            {t('upload.duplicate')}
          </Badge>
        ) : item.status === 'queued' ? (
          <Badge variant="neutral">{t('status.queuedUpload')}</Badge>
        ) : (
          <StatusBadge status={item.status === 'processing' ? 'processing' : 'ready'} />
        )}
      </TableCell>

      <TableCell>
        {item.status === 'ready' && document ? (
          <QrImage src={document.qr_url} documentName={document.original_name} size={48} />
        ) : (
          <div className="h-12 w-12" aria-hidden="true" />
        )}
      </TableCell>

      <TableCell>
        {item.status === 'ready' && document ? <Guid value={document.id} short /> : null}
      </TableCell>

      <TableCell>
        <div className="flex flex-wrap items-center gap-1">
          {item.status === 'ready' && document ? (
            <>
              {document.public_token ? (
                <CopyButton
                  value={`${import.meta.env.VITE_PUBLIC_BASE_URL ?? window.location.origin}/v/${document.public_token}`}
                  label={t('upload.copyUrl')}
                  successMessage={t('upload.urlCopied')}
                />
              ) : null}
              <Button
                variant="ghost"
                size="iconSm"
                aria-label={t('upload.print')}
                onClick={() => onPrint(item)}
              >
                <Printer size={16} aria-hidden="true" />
              </Button>
              <Button variant="ghost" size="iconSm" aria-label={t('upload.view')} asChild>
                <Link to={`/documents?document=${document.id}`}>
                  <Eye size={16} aria-hidden="true" />
                </Link>
              </Button>
            </>
          ) : null}

          {item.status === 'error' ? (
            <Button variant="outline" size="sm" onClick={() => onRetry(item.id)}>
              <ArrowClockwise size={16} aria-hidden="true" />
              {t('common.retry')}
            </Button>
          ) : null}

          <Button
            variant="ghost"
            size="iconSm"
            aria-label={t('upload.removeFromBatch', { name: item.name })}
            onClick={() => onRemove(item.id)}
          >
            <Trash size={16} aria-hidden="true" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}
