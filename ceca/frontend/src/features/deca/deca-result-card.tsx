import { Printer } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import { CopyButton } from '@/components/common/copy-button'
import { Guid } from '@/components/common/guid'
import { QrImage } from '@/components/common/qr-image'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from '@/lib/i18n'
import type { DocumentSummary } from '@/lib/types'

export function DecaResultCard({
  document,
  onQueuePrint,
  queueing,
}: {
  document: DocumentSummary
  onQueuePrint: () => void
  queueing?: boolean
}) {
  const { t } = useI18n()
  const publicUrl = document.public_token
    ? `${import.meta.env.VITE_PUBLIC_BASE_URL ?? window.location.origin}/v/${document.public_token}`
    : null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('deca.generated')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <QrImage src={document.qr_url} documentName={document.original_name} size={120} />
        <div className="flex min-w-0 flex-col gap-2">
          <p className="font-medium">{document.original_name}</p>
          <Guid value={document.id} />
          {publicUrl ? (
            <p className="flex items-center gap-2 text-sm">
              <span className="estampa-mono truncate text-muted-foreground">{publicUrl}</span>
              <CopyButton value={publicUrl} label={t('upload.copyUrl')} />
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={onQueuePrint} disabled={queueing}>
              <Printer size={20} aria-hidden="true" />
              {t('deca.sendToPrint')}
            </Button>
            <Button variant="outline" asChild>
              <Link to={`/documents?document=${document.id}`}>{t('deca.openInDocuments')}</Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
