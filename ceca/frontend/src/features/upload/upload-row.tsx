import { ArrowClockwise, Eye, Printer, Prohibit, Trash, WarningCircle } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { ComplianceBadge, StatusBadge } from '@/components/common/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { TableCell, TableRow } from '@/components/ui/table'
import { formatBytes, formatDate, truncateMiddle } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import { WARNING_DUPLICATE } from '@/lib/types'
import { isDuplicate, isPrintable, isScan, type BatchItem } from './use-upload-batch'

export function UploadRow({
  item,
  onRetry,
  onRemove,
  onPrint,
}: {
  item: BatchItem
  onRetry: (id: string) => void
  onRemove: (id: string) => void
  onPrint: (item: BatchItem) => void
}) {
  const { t, locale } = useI18n()
  const document = item.document
  const printable = isPrintable(item)
  const duplicateWarning = item.warnings.find((warning) => warning.code === WARNING_DUPLICATE)

  return (
    <TableRow className="estampa-row-enter align-top">
      <TableCell className="max-w-56">
        <p className="font-medium" title={item.name}>
          {truncateMiddle(item.name)}
        </p>
        <p className="text-meta text-muted-foreground">{formatBytes(item.size, locale)}</p>

        {/* Avisos en linea: icono + texto del color del estado. Sin caja: el
            aviso es informacion, no una tarjeta dentro de otra. */}
        {isDuplicate(item) ? (
          <p className="mt-2 flex items-start gap-1.5 text-sm text-warning-text">
            <WarningCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
            {t('upload.duplicateWarning', {
              date: formatDate(String(duplicateWarning?.params.uploaded_at ?? ''), locale),
            })}
          </p>
        ) : null}

        {/* docs/DECA.md §1: un escaneo no produce un DeCA valido. El aviso y la
            via correcta se mantienen enteros; solo pierden el marco. */}
        {isScan(item) ? (
          <>
            <p className="mt-2 flex items-start gap-1.5 text-sm text-destructive-text">
              <Prohibit size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
              {t('upload.notADecaWarning')}
            </p>
            <Button size="sm" variant="link" className="px-0" asChild>
              <Link to="/deca/new">{t('upload.generateInstead')}</Link>
            </Button>
          </>
        ) : null}
      </TableCell>

      <TableCell className="min-w-44">
        {item.status === 'uploading' ? (
          <div className="flex flex-col gap-1">
            <Progress
              value={item.progress}
              aria-label={t('upload.progressLabel', { name: item.name })}
            />
            <span className="text-meta text-muted-foreground">
              {t('upload.uploadingPercent', { percent: item.progress })}
            </span>
          </div>
        ) : item.status === 'rejected' || item.status === 'error' ? (
          <div className="flex flex-col gap-1">
            <Badge variant="destructive">
              <WarningCircle size={14} aria-hidden="true" />
              {t('status.failed')}
            </Badge>
            {/* El mensaje ya SALE del codigo: repetirlo debajo en mono no
                anade informacion, solo ruido. */}
            <span className="text-meta text-destructive-text">
              {item.errorMessage ?? t(`upload.errorCodes.${item.errorCode ?? 'UNKNOWN_ERROR'}`)}
            </span>
          </div>
        ) : item.status === 'queued' ? (
          <Badge variant="neutral">{t('status.queuedUpload')}</Badge>
        ) : (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge status={item.status === 'processing' ? 'processing' : 'ready'} />
            {document ? <ComplianceBadge status={document.compliance_status} /> : null}
          </div>
        )}
      </TableCell>

      <TableCell>
        {item.status === 'ready' && document ? (
          <QrImage documentId={document.id} documentName={document.original_filename} size={48} />
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
              {/* Un escaneo NO ofrece etiqueta: no es un DeCA valido. */}
              {printable ? (
                <Button
                  variant="ghost"
                  size="iconSm"
                  aria-label={t('upload.print')}
                  onClick={() => onPrint(item)}
                >
                  <Printer size={16} aria-hidden="true" />
                </Button>
              ) : null}
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
