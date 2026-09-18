import { expect, test } from '@playwright/test'
import { ADMIN, apiLogin, ensureLiveDocument, loginUi, shot, shots, toSpaUrl } from './helpers'

/**
 * 5. Visor publico por QR, en movil y sin sesion. Luego una revision con
 * motivo: la URL antigua deja de servir y es indistinguible de un token
 * inventado (mismo HTML, misma respuesta del backend).
 */
test('visor publico movil, revision con motivo, URL antigua igual que un token inventado', async ({
  browser,
  request,
  baseURL,
}) => {
  const session = await apiLogin(request, ADMIN)
  const { document, source } = await ensureLiveDocument(request, session)
  test.info().annotations.push({ type: 'documento', description: `${document.id} (${source})` })
  expect(document.public_url, 'public_url del documento').toBeTruthy()
  const publicUrl = toSpaUrl(document.public_url!, baseURL!)

  // Contexto NUEVO: sin cookies, sin storage, viewport de movil.
  const mobile = await browser.newContext({
    viewport: { width: 375, height: 812 },
    isMobile: true,
    hasTouch: true,
    locale: 'es-ES',
  })
  const page = await mobile.newPage()
  const viewResponse = page.waitForResponse(
    (response) => response.url() === publicUrl && response.request().resourceType() === 'fetch',
  )
  await page.goto(publicUrl)
  const view = await viewResponse
  expect(
    view.status(),
    `GET /v/{token} (JSON) respondio ${view.status()}: ${await view.text()}`,
  ).toBe(200)

  // Sin app shell: ni barra lateral, ni menu, ni navegacion de la app.
  await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Abrir el menú' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Subir PDFs' })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Centro de trabajo' })).toHaveCount(0)

  // Cabecera minima (48px) con el nombre del documento.
  const header = page.locator('header')
  await expect(header).toBeVisible()
  await expect(header).toContainText(document.original_filename)
  const headerBox = (await header.boundingBox())!
  expect(headerBox.height).toBeLessThanOrEqual(56)

  // Boton principal >= 48px de alto, un toque hasta el PDF.
  const cta = page.getByRole('link', { name: 'Abrir o descargar' })
  await expect(cta).toBeVisible()
  const ctaBox = (await cta.boundingBox())!
  expect(ctaBox.height).toBeGreaterThanOrEqual(48)
  expect(await cta.getAttribute('href')).toMatch(/\/v\/[\w-]+\/file$/)

  // El PDF se pinta (pdf.js) o se ofrece el fallback de descarga.
  await expect
    .poll(
      async () =>
        (await page.locator('canvas[role="img"]').count()) > 0 ||
        (await page.getByText('No se ha podido mostrar el PDF').count()) > 0,
      { timeout: 45_000, message: 'pdf.js o fallback' },
    )
    .toBe(true)
  const rendered = (await page.locator('canvas[role="img"]').count()) > 0
  test.info().annotations.push({ type: 'visor', description: rendered ? 'pdf.js' : 'fallback descarga' })
  await expect(page.getByText(/Emitido el \d{2}\/\d{2}\/\d{4}/)).toBeVisible()

  // Sin scroll horizontal en 375.
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth)

  // Cabeceras del fichero publico: inline, noindex, sin cache.
  const file = await request.get(`${publicUrl}/file`)
  expect(file.status()).toBe(200)
  expect(file.headers()['content-type']).toContain('application/pdf')
  expect(file.headers()['content-disposition'] ?? '').toMatch(/inline/)
  expect(file.headers()['x-robots-tag'] ?? '').toMatch(/noindex/)
  expect(file.headers()['cache-control'] ?? '').toMatch(/no-store/)

  await shots(page, '05-visor-publico')
  await page.setViewportSize({ width: 375, height: 812 })

  // Revision con motivo, desde la interfaz, con sesion de admin.
  const adminContext = await browser.newContext()
  const admin = await adminContext.newPage()
  await loginUi(admin, ADMIN)
  await admin.goto(`/deca/${document.id}`)
  await expect(admin.getByRole('heading', { name: 'Datos del DeCA' })).toBeVisible()
  const reason = admin.getByLabel(/Motivo de la modificación/)
  await expect(reason).toBeVisible()
  await admin.locator('[data-field="matricula_vehiculo"]').fill('5678 XYZ')
  await reason.fill('Corrección de matrícula tras control en carretera')
  const revisionResponse = admin.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/documents/${document.id}/revisions`) &&
      response.request().method() === 'POST',
  )
  await admin.getByRole('button', { name: 'Crear una revisión' }).click()
  const revision = await revisionResponse
  expect([200, 201], `POST /documents/{id}/revisions: ${await revision.text()}`).toContain(revision.status())
  const revised = await revision.json()
  expect(revised.revision).toBeGreaterThan(document.revision)
  expect(revised.id).not.toBe(document.id)
  await expect(admin.getByText('Revisión creada')).toBeVisible()
  await expect(admin).toHaveURL(new RegExp(`document=${document.id}`))
  // La antigua queda marcada como sustituida en su panel.
  await expect(admin.getByRole('dialog').getByText('Sustituido por una revisión')).toBeVisible()
  await shots(admin, '05-revision-creada')
  await adminContext.close()

  // La URL antigua ya no sirve...
  await page.goto(publicUrl)
  await expect(page.getByRole('heading', { name: 'Documento no disponible' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Abrir o descargar' })).toHaveCount(0)
  const oldHtml = await page.locator('main').innerHTML()
  await shot(page, '05-visor-no-disponible')

  // ...y es IDENTICA a la de un token inventado.
  const fakeUrl = `${baseURL}/v/e2e-token-inventado-${Date.now()}`
  await page.goto(fakeUrl)
  await expect(page.getByRole('heading', { name: 'Documento no disponible' })).toBeVisible()
  const fakeHtml = await page.locator('main').innerHTML()
  expect(oldHtml).toBe(fakeHtml)

  // Tambien en el backend: mismo codigo y mismo cuerpo.
  const oldJson = await request.get(publicUrl, { headers: { Accept: 'application/json' } })
  const fakeJson = await request.get(fakeUrl, { headers: { Accept: 'application/json' } })
  expect(oldJson.status()).toBe(404)
  expect(fakeJson.status()).toBe(404)
  expect(await oldJson.text()).toBe(await fakeJson.text())
  const oldFile = await request.get(`${publicUrl}/file`)
  const fakeFile = await request.get(`${fakeUrl}/file`)
  expect(oldFile.status()).toBe(fakeFile.status())
  expect(await oldFile.text()).toBe(await fakeFile.text())

  await mobile.close()
})
