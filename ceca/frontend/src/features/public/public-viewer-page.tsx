import { useQuery } from '@tanstack/react-query'
import { DownloadSimple, Prohibit } from '@phosphor-icons/react'
import { useParams } from 'react-router-dom'
import { ComplianceBadge } from '@/components/common/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { request } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import * as routes from '@/lib/routes'
import type { PublicDocumentView } from '@/lib/types'
import { PdfViewer } from './pdf-viewer'

/**
 * Estado indistinguible para "retirado", "revocado" y "no encontrado".
 * CLAUDE.md: `/v/{token}` no revela si un token no existe o fue revocado; el
 * backend ya responde lo mismo a los tres, y aqui se pinta un unico componente
 * con un unico texto, para que tampoco se pueda inferir por el HTML.
 */
export function DocumentUnavailable() {
  const { t } = useI18n()
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <Prohibit size={48} aria-hidden="true" className="text-muted-foreground" />
      <h1 className="text-h2 font-semibold">{t('public.unavailableTitle')}</h1>
      <p className="text-base text-muted-foreground">{t('public.unavailableBody')}</p>
    </main>
  )
}

export default function PublicViewerPage() {
  const { token } = useParams()
  const { t, locale } = useI18n()

  const document = useQuery({
    queryKey: ['public', token],
    queryFn: () =>
      // `skipAuth`: el visor publico no manda token ni intenta refrescar sesion.
      request<PublicDocumentView>(routes.publicView({ token: token ?? '' }), { skipAuth: true }),
    retry: false,
    enabled: Boolean(token),
  })

  if (document.isPending) {
    return (
      <div className="flex min-h-dvh flex-col" aria-busy="true">
        <div
          className="flex items-center gap-2 border-b border-border px-4"
          style={{ height: 'var(--public-header)' }}
        >
          <Skeleton className="h-5 w-48" />
        </div>
        <div className="flex-1 p-4">
          <Skeleton className="h-[70vh] w-full" />
        </div>
      </div>
    )
  }

  // Cualquier fallo -> el mismo estado. No se distingue 404 de retirado.
  if (document.isError || !document.data) return <DocumentUnavailable />

  const data = document.data

  return (
    <div className="flex min-h-dvh flex-col bg-background text-base">
      {/* Cabecera 48px, sin app shell (public-viewer.md). */}
      <header
        className="flex shrink-0 items-center gap-3 border-b border-border bg-card px-4"
        style={{ height: 'var(--public-header)' }}
      >
        <span className="font-semibold">{data.site_name ?? t('app.name')}</span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">
          {data.original_filename}
        </span>
      </header>

      <main className="flex flex-1 flex-col gap-3 px-4 py-4">
        {/* Un escaneo nunca se presenta como DeCA valido, tampoco en carretera. */}
        <ComplianceBadge status={data.compliance_status} />
        <PdfViewer
          token={token ?? ''}
          fileName={data.original_filename}
          fileHref={data.file_url}
        />
      </main>

      <footer className="sticky bottom-0 flex flex-col items-center gap-2 border-t border-border bg-card px-4 py-3">
        <Button size="public" asChild>
          <a href={data.file_url} target="_blank" rel="noopener noreferrer">
            <DownloadSimple size={24} aria-hidden="true" />
            {t('public.openOrDownload')}
          </a>
        </Button>
        <p className="text-sm text-muted-foreground">
          {t('public.issuedOn', { date: formatDate(data.issued_at, locale) })} ·{' '}
          {t('public.revisionN', { n: data.revision })}
        </p>
      </footer>
    </div>
  )
}
