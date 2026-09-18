import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import {
  ADMIN,
  apiClearQueue,
  apiListDocuments,
  apiLogin,
  ensureLiveDocument,
  loginUi,
  settle,
  toSpaUrl,
  useDarkTheme,
} from './helpers'

const BLOCKING = new Set(['serious', 'critical'])

/** Cero violaciones `serious`/`critical` (MASTER §10). */
async function audit(page: Page, label: string) {
  // Con una animacion a medias (sheet entrando, fila apareciendo) axe mide
  // colores a medio fundir y da falsos positivos de contraste.
  await settle(page)
  const results = await new AxeBuilder({ page }).analyze()
  const blocking = results.violations
    .filter((violation) => BLOCKING.has(violation.impact ?? ''))
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      nodes: violation.nodes.slice(0, 4).map((node) => node.target.join(' ')),
    }))
  expect(blocking, `axe ${label}`).toEqual([])
}

const THEMES = ['light', 'dark'] as const

for (const theme of THEMES) {
  test(`axe (${theme}): login, documentos, subida, generar, cola y visor publico`, async ({
    page,
    browser,
    request,
    baseURL,
  }) => {
    if (theme === 'dark') await useDarkTheme(page)

    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Entrar en Estampa' })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await audit(page, `login ${theme}`)

    // Cola con contenido: dos documentos por API, para auditar la vista previa.
    const session = await apiLogin(request, ADMIN)
    await apiClearQueue(request, session)
    const documents = (await apiListDocuments(request, session)).items.filter(
      (document) => document.status === 'ready' && !document.withdrawn_at && !document.superseded_at,
    )
    const queued = await request.post('/api/v1/printing/queue/', {
      headers: session.headers,
      data: { document_ids: documents.slice(0, 2).map((document) => document.id) },
    })
    expect(queued.status()).toBe(201)

    await loginUi(page, ADMIN)
    const screens: [string, string][] = [
      ['/documents', 'Documentos'],
      ['/upload', 'Subir PDFs'],
      ['/deca/new', 'Generar DeCA'],
      ['/printing', 'Cola de impresión'],
    ]
    for (const [path, heading] of screens) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
      await page.waitForLoadState('networkidle')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await audit(page, `${path} ${theme}`)
    }
    // El panel lateral del documento tambien.
    await page.goto('/documents')
    await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.waitForLoadState('networkidle')
    await audit(page, `/documents (panel) ${theme}`)
    await apiClearQueue(request, session)

    // Visor publico, sin sesion, en movil.
    const { document } = await ensureLiveDocument(request, session)
    const mobile = await browser.newContext({ viewport: { width: 375, height: 812 }, locale: 'es-ES' })
    const viewer = await mobile.newPage()
    if (theme === 'dark') await useDarkTheme(viewer)
    await viewer.goto(toSpaUrl(document.public_url!, baseURL!))
    await expect
      .poll(
        async () =>
          (await viewer.locator('canvas[role="img"]').count()) > 0 ||
          (await viewer.getByText('No se ha podido mostrar el PDF').count()) > 0 ||
          (await viewer.getByRole('heading', { name: 'Documento no disponible' }).count()) > 0,
        { timeout: 45_000 },
      )
      .toBe(true)
    const state = (await viewer.getByRole('heading', { name: 'Documento no disponible' }).count()) > 0
      ? 'no disponible'
      : 'documento'
    test.info().annotations.push({ type: 'visor-publico', description: state })
    await audit(viewer, `visor publico (${state}) ${theme}`)
    await mobile.close()
  })
}
