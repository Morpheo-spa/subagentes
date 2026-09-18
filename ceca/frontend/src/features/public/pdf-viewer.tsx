import { useEffect, useRef, useState } from 'react'
import { DownloadSimple } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { requestBlob } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import * as routes from '@/lib/routes'

/**
 * Visor pdf.js con fallback a descarga (public-viewer.md).
 * pdf.js se carga bajo demanda: en movil y con mala red, primero la pagina.
 *
 * El PDF lo sirve `GET /v/{token}/file` por streaming; la URL del storage no
 * sale de la API (CLAUDE.md §3.9).
 */
export function PdfViewer({
  token,
  fileName,
  fileHref,
}: {
  token: string
  fileName: string
  fileHref: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')

  useEffect(() => {
    let cancelled = false
    const container = containerRef.current

    const render = async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          'pdfjs-dist/build/pdf.worker.min.mjs',
          import.meta.url,
        ).toString()

        // `skipAuth`: el visor publico no manda token ni refresca sesion.
        const blob = await requestBlob(routes.publicFile({ token }), { skipAuth: true })
        const data = await blob.arrayBuffer()
        if (cancelled || !container) return

        const document_ = await pdfjs.getDocument({ data }).promise
        container.replaceChildren()

        for (let pageNumber = 1; pageNumber <= document_.numPages; pageNumber += 1) {
          const page = await document_.getPage(pageNumber)
          const width = container.clientWidth || 360
          const base = page.getViewport({ scale: 1 })
          const viewport = page.getViewport({ scale: width / base.width })
          const canvas = window.document.createElement('canvas')
          canvas.width = Math.floor(viewport.width)
          canvas.height = Math.floor(viewport.height)
          canvas.style.width = '100%'
          canvas.style.height = 'auto'
          canvas.setAttribute('role', 'img')
          canvas.setAttribute('aria-label', t('public.pageOf', { page: pageNumber, name: fileName }))
          const context = canvas.getContext('2d')
          if (!context) throw new Error('no 2d context')
          container.append(canvas)
          await page.render({ canvasContext: context, viewport }).promise
          if (cancelled) return
        }

        if (!cancelled) setState('ready')
      } catch {
        if (!cancelled) setState('failed')
      }
    }

    void render()
    return () => {
      cancelled = true
    }
  }, [token, fileName, t])

  return (
    <div className="flex w-full flex-col gap-4">
      {state === 'loading' ? <Skeleton className="h-[60vh] w-full" /> : null}

      {state === 'failed' ? (
        <div className="flex flex-col items-center gap-4 rounded-lg border border-border bg-card p-6 text-center">
          <p className="text-base">{t('public.viewerFailed')}</p>
          <Button size="public" asChild>
            <a href={fileHref} download={fileName}>
              <DownloadSimple size={24} aria-hidden="true" />
              {t('public.download')}
            </a>
          </Button>
        </div>
      ) : null}

      <div ref={containerRef} className="flex w-full flex-col gap-2" />
    </div>
  )
}
