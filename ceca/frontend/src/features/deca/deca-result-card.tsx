import { Printer } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import { ComplianceBadge } from '@/components/common/status-badge'
import { CopyButton } from '@/components/common/copy-button'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from '@/lib/i18n'
import type { DocumentRead } from '@/lib/types'

export function DecaResultCard({
  document,
  onQueuePrint,
  queueing,
}: {
  document: DocumentRead
  onQueuePrint: () => void
  queueing?: boolean
}) {
  const { t } = useI18n()
  // La URL publica la compone el backend con el token de compartir.
  const publicUrl = document.public_url

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('deca.generated')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <QrImage
          documentId={document.id}
          documentName={document.original_filename}
          size={120}
        />
        <div className="flex min-w-0 flex-col gap-2">
          <p className="font-medium">{document.original_filename}</p>
          <ComplianceBadge status={document.compliance_status} />
          <Guid value={document.id} />
          {publicUrl ? (
            <p className="flex items-center gap-2 text-sm">
              <span className="estampa-mono truncate text-muted-foreground">{publicUrl}</span>
              <CopyButton value={publicUrl} label={t('upload.copyUrl')} />
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {/* Un escaneo no se ofrece para etiqueta como si fuera valido. */}
            {document.is_valid_deca ? (
              <Button onClick={onQueuePrint} disabled={queueing}>
                <Printer size={20} aria-hidden="true" />
                {t('deca.sendToPrint')}
              </Button>
            ) : null}
            <Button variant="outline" asChild>
              <Link to={`/documents?document=${document.id}`}>{t('deca.openInDocuments')}</Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
