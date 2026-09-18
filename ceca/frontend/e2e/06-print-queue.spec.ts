import { expect, test } from '@playwright/test'
import {
  ADMIN,
  apiClearQueue,
  apiListDocuments,
  apiLogin,
  apiUpload,
  loginUi,
  nativePdf,
  shot,
  shots,
  type ApiDocument,
} from './helpers'

/**
 * 6. Cola de impresion: dos documentos, plantilla de hoja, "empezar en la
 * posicion 3", vista previa paginada, Imprimir + confirmar, trabajo en el
 * historico y cola vacia tras "si se imprimio".
 */
test('cola de impresion de principio a fin', async ({ page, request, context }) => {
  const session = await apiLogin(request, ADMIN)
  await apiClearQueue(request, session)

  // Dos documentos vigentes que no sean escaneos.
  const list = await apiListDocuments(request, session)
  const usable = (documents: ApiDocument[]) =>
    documents.filter(
      (document) =>
        document.status === 'ready' &&
        !document.withdrawn_at &&
        !document.superseded_at &&
        document.origin !== 'uploaded_scanned',
    )
  let candidates = usable(list.items)
  while (candidates.length < 2) {
    await apiUpload(request, session, `e2e-cola-${Date.now()}.pdf`, nativePdf(`cola ${Date.now()}`))
    candidates = usable((await apiListDocuments(request, session)).items)
  }
  const [docA, docB] = candidates

  // Ventanas que abra la impresion (render del folio): se cierran solas.
  context.on('page', (popup) => void popup.close().catch(() => undefined))

  await loginUi(page, ADMIN)
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Documentos' })).toBeVisible()

  // Seleccion multiple -> barra flotante -> "Añadir a la cola".
  for (const document of [docA, docB]) {
    const row = page.locator('table tbody tr').filter({ hasText: document.id.slice(0, 8).toUpperCase() })
    await expect(row, `fila de ${document.original_filename}`).toHaveCount(1)
    await row.getByRole('checkbox').check()
  }
  const bulk = page.getByRole('region', { name: 'Acciones sobre la selección' })
  await expect(bulk).toContainText('2 seleccionados')
  const queueAdd = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/printing/queue/') && response.request().method() === 'POST',
  )
  await bulk.getByRole('button', { name: 'Añadir a la cola de impresión' }).click()
  expect((await queueAdd).status()).toBe(201)
  await expect(page.getByText('Añadido a la cola (2)')).toBeVisible()

  // La cola.
  await page.goto('/printing')
  await expect(page.getByRole('heading', { name: 'Cola de impresión' })).toBeVisible()
  const queue = page.getByRole('region', { name: 'En cola' })
  await expect(queue.locator('li')).toHaveCount(2)
  await expect(queue.getByRole('button', { name: /^Subir .* en la cola$/ })).toHaveCount(2)
  await expect(queue.getByRole('button', { name: /^Bajar .* en la cola$/ })).toHaveCount(2)

  // Plantilla de hoja: el Select va agrupado por "una por pagina" / "hoja".
  const template = page.getByRole('combobox', { name: 'Plantilla' })
  await template.click()
  const listbox = page.getByRole('listbox')
  await expect(listbox.getByText('Una etiqueta por página')).toBeVisible()
  await expect(listbox.getByText('Hoja cuadriculada')).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Modo' })).toHaveCount(0)
  await listbox.getByRole('option', { name: /A4 21 etiquetas/ }).click()
  await expect(template).toContainText('A4 21 etiquetas')

  // "Empezar en la posicion 3" solo aparece con hojas de varias etiquetas.
  const start = page.getByLabel('Empezar en la posición')
  await expect(start).toBeVisible()
  await start.fill('3')
  await expect(start).toHaveValue('3')

  // Vista previa paginada: una hoja de 21 huecos, dos vacios delante.
  const sheets = page.locator('.estampa-sheet-page')
  await expect(sheets).toHaveCount(1)
  const slots = sheets.first().locator(':scope > *')
  await expect(slots).toHaveCount(21)
  await expect(slots.nth(0)).toHaveAttribute('aria-hidden', 'true')
  await expect(slots.nth(1)).toHaveAttribute('aria-hidden', 'true')
  expect(await slots.nth(2).getAttribute('aria-hidden')).toBeNull()
  expect(await slots.nth(3).getAttribute('aria-hidden')).toBeNull()
  await expect(slots.nth(4)).toHaveAttribute('aria-hidden', 'true')
  await expect(sheets.first().getByRole('img', { name: /^Código QR del documento/ })).toHaveCount(2)
  await expect(page.getByText('2 etiquetas · 1 páginas')).toBeVisible()

  // Con "una etiqueta por pagina" no hay posicion inicial y salen dos paginas.
  await template.click()
  await page.getByRole('listbox').getByRole('option', { name: /Térmica|Termica/ }).click()
  await expect(page.getByLabel('Empezar en la posición')).toHaveCount(0)
  await expect(sheets).toHaveCount(2)
  await expect(page.getByText('2 etiquetas · 2 páginas')).toBeVisible()
  await template.click()
  await page.getByRole('listbox').getByRole('option', { name: /A4 21 etiquetas/ }).click()
  await expect(sheets).toHaveCount(1)
  await expect(page.getByLabel('Empezar en la posición')).toHaveValue('3')

  await page.getByLabel('Nombre del trabajo').fill('Etiquetadora e2e')
  await shots(page, '06-cola')

  // Imprimir -> confirmar -> trabajo registrado ANTES de abrir la impresion.
  await page.getByRole('button', { name: 'Imprimir', exact: true }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Imprimir la cola' })
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('2 etiquetas en 1 páginas')
  await expect(confirm).toContainText('A4 21 etiquetas')
  await shot(page, '06-cola-confirmar')
  const jobCreate = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/printing/jobs/') && response.request().method() === 'POST',
  )
  await confirm.getByRole('button', { name: 'Imprimir' }).click()
  const jobResponse = await jobCreate
  expect(jobResponse.status(), `POST /printing/jobs/: ${await jobResponse.text()}`).toBe(201)
  const job = await jobResponse.json()
  expect(job.template_code).toBe('a4_3x7')
  expect(job.start_position).toBe(3)
  expect(job.label_count).toBe(2)
  expect(job.printer_name).toBe('Etiquetadora e2e')
  expect(job.items.map((item: { document_id: string }) => item.document_id).sort()).toEqual(
    [docA.id, docB.id].sort(),
  )
  await expect(page.getByText('Trabajo de impresión registrado')).toBeVisible()

  // "¿Se imprimio bien?" -> Si -> cola vacia.
  const ask = page.getByRole('alertdialog', { name: '¿Se imprimió bien?' })
  await expect(ask).toBeVisible()
  await shot(page, '06-cola-se-imprimio')
  const confirmCall = page.waitForResponse(
    (response) => response.url().endsWith(`/api/v1/printing/jobs/${job.id}/confirm`),
  )
  await ask.getByRole('button', { name: 'Sí, se imprimió' }).click()
  expect((await confirmCall).status()).toBe(200)
  await expect(page.getByText('Cola vaciada')).toBeVisible()
  await expect(page.getByText('La cola está vacía')).toBeVisible()

  // Historico: el trabajo consta como impreso; la cola esta vacia de verdad.
  const jobs = await (await request.get('/api/v1/printing/jobs/', { headers: session.headers })).json()
  const recorded = (jobs.items as { id: string; status: string; confirmed_at: string | null }[]).find(
    (entry) => entry.id === job.id,
  )
  expect(recorded, 'el trabajo esta en el historico').toBeDefined()
  expect(recorded!.status).toBe('printed')
  expect(recorded!.confirmed_at).toBeTruthy()
  const remaining = await (await request.get('/api/v1/printing/queue/', { headers: session.headers })).json()
  expect(remaining.total).toBe(0)

  // Y sigue vacia tras recargar (la cola es del servidor, no del navegador).
  await page.reload()
  await expect(page.getByText('La cola está vacía')).toBeVisible()
  await shots(page, '06-cola-vacia')
})
