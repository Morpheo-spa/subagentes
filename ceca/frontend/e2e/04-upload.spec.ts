import { expect, test } from '@playwright/test'
import {
  ADMIN,
  apiDownloadFile,
  apiGenerate,
  apiGetDocument,
  apiLogin,
  apiUpload,
  loginUi,
  nativePdf,
  scanPdf,
  shots,
} from './helpers'

/**
 * 4. Subida. Un PDF nativo con el mismo hash que uno archivado se marca como
 * duplicado; un "escaneo" (sin capa de texto) se archiva pero se dice con todas
 * las letras que NO es un DeCA valido y no se le ofrece etiqueta.
 */
test('nativo duplicado con aviso, escaneo no valido sin etiqueta, aria-live y boton de seleccion', async ({
  page,
  request,
}) => {
  const session = await apiLogin(request, ADMIN)

  // El PDF nativo: el del DeCA generado por API (descargado con el token). Si
  // `generate` no responde, un nativo subido por API: en ambos casos el archivo
  // ya existe con ese hash antes de subirlo por la interfaz.
  const generated = await apiGenerate(request, session)
  let native: Buffer
  if (generated.document) {
    native = await apiDownloadFile(request, session, generated.document.id)
    test.info().annotations.push({ type: 'pdf-nativo', description: `descargado de ${generated.document.id}` })
  } else {
    native = nativePdf(`Albaran e2e duplicado ${Date.now()}`)
    const uploaded = await apiUpload(request, session, 'e2e-original.pdf', native)
    expect(uploaded.document, 'subida nativa previa por API').not.toBeNull()
    test.info().annotations.push({
      type: 'pdf-nativo',
      description: `generate respondio ${generated.status}; nativo subido por API ${uploaded.document!.id}`,
    })
  }
  expect(native.subarray(0, 5).toString('latin1')).toBe('%PDF-')

  await loginUi(page, ADMIN)
  await expect(page.getByRole('heading', { name: 'Subir PDFs' })).toBeVisible()

  // WCAG 2.2: el arrastre nunca es la unica via.
  const selectButton = page.getByRole('button', { name: 'Seleccionar archivos' })
  await expect(selectButton).toBeVisible()
  const input = page.locator('input[type="file"]')
  await expect(input).toHaveCount(1)
  expect(await input.getAttribute('accept')).toContain('pdf')
  expect(await input.getAttribute('multiple')).not.toBeNull()

  // El anuncio de la pagina, no la region de toasts (que tambien es polite).
  const live = page.locator('main [aria-live="polite"][role="status"]')
  await expect(live).toHaveCount(1)
  await expect(live).toHaveText('')

  const scanSalt = String(Date.now())
  await input.setInputFiles([
    { name: 'nativo.pdf', mimeType: 'application/pdf', buffer: native },
    { name: 'escaneo.pdf', mimeType: 'application/pdf', buffer: scanPdf(scanSalt) },
  ])

  const rows = page.locator('table tbody tr')
  await expect(rows).toHaveCount(2)
  const nativeRow = rows.filter({ hasText: 'nativo.pdf' })
  const scanRow = rows.filter({ hasText: 'escaneo.pdf' })

  // "N de M listos" por aria-live, sin un toast por fichero.
  await expect(live).toHaveText('2 de 2 listos', { timeout: 60_000 })
  await expect(page.getByText('2 archivos · 2 listos · 0 con error')).toBeVisible()

  // Nativo: duplicado por hash, con aviso y fecha.
  await expect(nativeRow.getByText(/Ya existe un archivo idéntico, subido el \d{2}\/\d{2}\/\d{4}/)).toBeVisible()
  await expect(nativeRow.getByText('Listo')).toBeVisible()

  // Escaneo: archivado, pero NUNCA valido como DeCA ni con etiqueta.
  await expect(scanRow.getByText('Listo')).toBeVisible()
  await expect(scanRow.getByText('Escaneo: no válido')).toBeVisible()
  await expect(scanRow.getByText(/parece un escaneo o una foto: no es un DeCA válido/)).toBeVisible()
  await expect(scanRow.getByText('Válido como DeCA')).toHaveCount(0)
  await expect(scanRow.getByRole('button', { name: 'Añadir a la cola de impresión' })).toHaveCount(0)
  await expect(scanRow.getByRole('link', { name: 'Generar un DeCA desde datos' })).toBeVisible()
  await expect(scanRow.getByRole('link', { name: 'Ver el documento' })).toBeVisible()
  // QR y GUID en ambas filas (se archivan las dos).
  await expect(nativeRow.getByRole('img', { name: /^Código QR del documento/ })).toBeVisible()
  await expect(scanRow.getByRole('img', { name: /^Código QR del documento/ })).toBeVisible()

  // La barra inferior no cuenta el escaneo como imprimible.
  const send = page.getByRole('button', { name: /Enviar a impresión \(\d+\)/ })
  await expect(send).toBeVisible()
  const printable = Number(/\((\d+)\)/.exec((await send.textContent()) ?? '')?.[1] ?? '-1')
  expect(printable, 'el escaneo no entra en "Enviar a impresión"').toBeLessThanOrEqual(1)
  if (printable === 0) await expect(send).toBeDisabled()

  await shots(page, '04-subida')

  // Lo que dice el backend de cada uno.
  const scanLink = await scanRow.getByRole('link', { name: 'Ver el documento' }).getAttribute('href')
  const scanId = /document=([\w-]+)/.exec(scanLink ?? '')?.[1]
  expect(scanId).toBeTruthy()
  const scanDocument = await apiGetDocument(request, session, scanId!)
  expect(scanDocument.origin).toBe('uploaded_scanned')
  expect(scanDocument.compliance_status).toBe('not_a_deca')
  expect(scanDocument.is_valid_deca).toBe(false)

  const nativeLink = await nativeRow.getByRole('link', { name: 'Ver el documento' }).getAttribute('href')
  const nativeId = /document=([\w-]+)/.exec(nativeLink ?? '')?.[1]
  const nativeDocument = await apiGetDocument(request, session, nativeId!)
  expect(nativeDocument.origin).toBe('uploaded_native')
})
