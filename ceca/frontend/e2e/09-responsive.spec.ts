import { expect, test } from '@playwright/test'
import {
  ADMIN,
  apiClearQueue,
  apiListDocuments,
  apiLogin,
  horizontalOverflow,
  loginUi,
  shots,
  WIDTHS,
} from './helpers'

const SCREENS: [string, string, string][] = [
  ['/documents', 'Documentos', 'documentos'],
  ['/upload', 'Subir PDFs', 'subida'],
  ['/deca/new', 'Generar DeCA', 'generar'],
  ['/printing', 'Cola de impresión', 'cola'],
]

/**
 * 9. Responsive (MASTER §5 y §12): sin scroll horizontal en 375 · 768 · 1024 ·
 * 1440; en 375 la tabla de documentos se convierte en cards.
 */
test('sin scroll horizontal en ningun ancho; tabla -> cards en 375', async ({ page, request }) => {
  const session = await apiLogin(request, ADMIN)
  await apiClearQueue(request, session)
  const documents = (await apiListDocuments(request, session)).items.filter(
    (document) => document.status === 'ready' && !document.withdrawn_at && !document.superseded_at,
  )
  expect(documents.length).toBeGreaterThan(0)
  const queued = await request.post('/api/v1/printing/queue/', {
    headers: session.headers,
    data: { document_ids: documents.slice(0, 2).map((document) => document.id) },
  })
  expect(queued.status()).toBe(201)

  const noOverflow = async (label: string) => {
    const overflow = await horizontalOverflow(page)
    expect(overflow.scrollWidth, `${label}: scrollWidth ${overflow.scrollWidth} > innerWidth ${overflow.innerWidth}`)
      .toBeLessThanOrEqual(overflow.innerWidth)
  }

  // Login, sin sesion.
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 900 })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Entrar en Estampa' })).toBeVisible()
    await noOverflow(`/login @${width}`)
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  await loginUi(page, ADMIN)

  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 900 })
    for (const [path, heading] of SCREENS) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
      await page.waitForLoadState('networkidle')
      await noOverflow(`${path} @${width}`)
    }
    // El panel del documento tampoco desborda.
    await page.goto('/documents')
    await page.waitForLoadState('networkidle')
    if (width < 768) {
      await page.locator('main ul li button').first().click()
    } else {
      await page.locator('table tbody tr').first().locator('td:nth-child(2) button').click()
    }
    await expect(page.getByRole('dialog')).toBeVisible()
    await noOverflow(`/documents (panel) @${width}`)
    await page.keyboard.press('Escape')
  }

  // 375: sin sidebar, menu en un boton, tabla -> cards.
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Documentos', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Abrir el menú' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toBeHidden()
  await expect(page.locator('table')).toBeHidden()
  const cards = page.locator('main ul > li')
  expect(await cards.count()).toBeGreaterThan(0)
  const firstCard = cards.first()
  await expect(firstCard.getByRole('button').first()).toBeVisible()
  await expect(firstCard.getByText(/Caduca el \d{2}\/\d{2}\/\d{4}/)).toBeVisible()
  await expect(firstCard.getByText(/Listo|Caduca pronto|Retirado|Error|Procesando/)).toBeVisible()
  // Los badges son pildoras, no barras a todo el ancho.
  const badge = firstCard.getByText(/Válido como DeCA|Faltan datos|Escaneo: no válido|Sustituido/).first()
  const badgeBox = (await badge.boundingBox())!
  const cardBox = (await firstCard.boundingBox())!
  expect(badgeBox.width).toBeLessThan(cardBox.width * 0.8)
  // Menu movil: la navegacion aparece en un Sheet.
  await page.getByRole('button', { name: 'Abrir el menú' }).click()
  await expect(page.getByRole('dialog').getByRole('link', { name: 'Documentos' })).toBeVisible()
  await page.keyboard.press('Escape')

  // 768: la tabla vuelve.
  await page.setViewportSize({ width: 768, height: 900 })
  await expect(page.locator('table')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Abrir el menú' })).toBeVisible()
  // 1024: sidebar fija.
  await page.setViewportSize({ width: 1024, height: 900 })
  await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Abrir el menú' })).toBeHidden()

  await page.setViewportSize({ width: 1440, height: 900 })
  for (const [path, heading, name] of SCREENS) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
    await page.waitForLoadState('networkidle')
    await shots(page, `09-${name}`)
  }
  await apiClearQueue(request, session)
})
