import { Printer } from '@phosphor-icons/react'
import { ComplianceBadge, StatusBadge } from '@/components/common/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { formatDate, isExpiringSoon, truncateMiddle } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { DocumentSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * documents.md: por debajo de 768px la tabla se convierte en cards con nombre,
 * estado, caduca y un boton. El GUID no entra: en el movil no se copia, y el
 * detalle lo tiene entero.
 */
export function DocumentsCards({
  documents,
  onOpen,
  onPrint,
}: {
  documents: DocumentSummary[]
  onOpen: (document: DocumentSummary) => void
  onPrint: (document: DocumentSummary) => void
}) {
  const { t, locale } = useI18n()

  return (
    <ul className="flex flex-col gap-3">
      {documents.map((document) => (
        <li key={document.id}>
          <Card className={cn(isExpiringSoon(document.expires_at) && 'border-l-4 border-l-warning')}>
            {/* `items-start`: los badges son pildoras, no barras a todo el ancho. */}
            <CardContent className="flex flex-col items-start gap-2 p-4">
              <button
                type="button"
                className="cursor-pointer text-left font-medium underline-offset-2 hover:underline"
                onClick={() => onOpen(document)}
              >
                {truncateMiddle(document.original_filename, 36)}
              </button>
              <StatusBadge status={document.status} expiresAt={document.expires_at} />
              <ComplianceBadge status={document.compliance_status} />
              <p className="text-meta text-muted-foreground">
                {t('documents.expiresOn', { date: formatDate(document.expires_at, locale) })}
              </p>
              {/* Un escaneo no se ofrece para etiqueta: no es un DeCA valido. */}
              {document.is_valid_deca ? (
                <Button variant="outline" onClick={() => onPrint(document)}>
                  <Printer size={20} aria-hidden="true" />
                  {t('documents.print')}
                </Button>
              ) : null}
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  )
}
