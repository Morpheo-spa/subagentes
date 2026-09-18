import { expect, test } from '@playwright/test'
import { ADMIN, DECA_VALUES, INVALID_NIF, loginUi, shots, VALID_CARGADOR_NIF } from './helpers'

interface CatalogField {
  code: string
  data_type: string
  is_required: boolean
  label_es: string
}

/**
 * 3. Generar DeCA. El formulario sale de `GET /deca/fields`; cargador
 * contractual y transportista efectivo son bloques separados; el error del
 * NIF se pinta junto al campo; el resultado es un DeCA valido con QR.
 */
test('formulario dinamico, NIF invalido junto al campo, genera un DeCA con QR', async ({ page }) => {
  await loginUi(page, ADMIN)

  const catalogResponse = page.waitForResponse((response) => response.url().includes('/api/v1/deca/fields'))
  await page.goto('/deca/new')
  await expect(page.getByRole('heading', { name: 'Generar DeCA' })).toBeVisible()
  const catalog = await catalogResponse
  expect(catalog.status(), 'GET /deca/fields').toBe(200)
  const fields = ((await catalog.json()).fields as CatalogField[]).sort((a, b) => a.code.localeCompare(b.code))
  expect(fields.length).toBeGreaterThan(0)

  // Cada campo del catalogo tiene su control, con su etiqueta visible.
  for (const field of fields) {
    const control = page.locator(`[data-field="${field.code}"]`)
    await expect(control, `control de ${field.code}`).toBeVisible()
    await expect(page.locator('label', { hasText: field.label_es }).first(), `label de ${field.code}`).toBeVisible()
  }

  // Dos bloques SEPARADOS y etiquetados (docs/DECA.md §3, deca-form.md).
  const cargador = page.locator('fieldset', { has: page.locator('legend', { hasText: 'Cargador contractual' }) })
  const transportista = page.locator('fieldset', {
    has: page.locator('legend', { hasText: 'Transportista efectivo' }),
  })
  await expect(cargador).toHaveCount(1)
  await expect(transportista).toHaveCount(1)
  await expect(cargador.locator('fieldset')).toHaveCount(0)
  await expect(transportista.locator('fieldset')).toHaveCount(0)
  await expect(cargador.locator('[data-field="cargador_nif"]')).toHaveCount(1)
  await expect(cargador.locator('[data-field="transportista_nif"]')).toHaveCount(0)
  await expect(transportista.locator('[data-field="transportista_nif"]')).toHaveCount(1)
  const cargadorBox = (await cargador.boundingBox())!
  const transportistaBox = (await transportista.boundingBox())!
  expect(cargadorBox.y + cargadorBox.height, 'el bloque del cargador termina antes de empezar el del transportista')
    .toBeLessThanOrEqual(transportistaBox.y)

  // NIF con digito de control incorrecto: error junto al campo, al blur.
  const nif = page.locator('[data-field="cargador_nif"]')
  await nif.fill(INVALID_NIF)
  await nif.press('Tab')
  const nifError = page.getByRole('alert').filter({ hasText: 'El NIF/CIF no es válido' })
  await expect(nifError).toBeVisible()
  await expect(nif).toHaveAttribute('aria-invalid', 'true')
  const describedBy = (await nif.getAttribute('aria-describedby')) ?? ''
  const errorId = await nifError.getAttribute('id')
  expect(describedBy.split(' '), 'aria-describedby del NIF apunta al mensaje').toContain(errorId)
  const nifBox = (await nif.boundingBox())!
  const errorBox = (await nifError.boundingBox())!
  expect(errorBox.y, 'el mensaje esta debajo del campo').toBeGreaterThanOrEqual(nifBox.y + nifBox.height - 1)
  expect(errorBox.y - (nifBox.y + nifBox.height), 'pegado al campo, no en otra parte').toBeLessThan(80)
  // Y ese error no se mezcla con el del transportista.
  await expect(transportista.getByRole('alert')).toHaveCount(0)
  await shots(page, '03-deca-nif-invalido')

  // Corregido: el error desaparece.
  await nif.fill(VALID_CARGADOR_NIF)
  await nif.press('Tab')
  await expect(nifError).toHaveCount(0)
  await expect(nif).toHaveAttribute('aria-invalid', 'false')

  // Relleno completo, guiado por el catalogo (no por una lista propia).
  for (const field of fields) {
    const value = DECA_VALUES[field.code]
    if (value === undefined) continue
    const control = page.locator(`[data-field="${field.code}"]`)
    if (field.data_type === 'enum') {
      await control.click()
      await page.getByRole('option', { name: value, exact: true }).click()
    } else {
      await control.fill(value)
    }
  }
  await expect(page.getByText(/Faltan \d+ campos obligatorios/)).toHaveCount(0)
  await expect(page.getByText('no pueden tener el mismo NIF')).toHaveCount(0)

  const generateResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/documents/generate') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Generar el PDF' }).click()
  const generated = await generateResponse
  expect(
    generated.status(),
    `POST /api/v1/documents/generate respondio ${generated.status()}: ${await generated.text()}`,
  ).toBe(201)
  const document = await generated.json()

  await expect(page.getByText('DeCA generado correctamente')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'DeCA generado' })).toBeVisible()
  expect(document.is_valid_deca, 'is_valid_deca en la respuesta').toBe(true)
  expect(document.compliance_status).toBe('compliant')
  expect(document.origin).toBe('generated')

  // Valido como DeCA, con el QR de verdad (imagen, no el hueco pendiente).
  // En esta pagina el unico badge, QR y URL publica son los del resultado.
  const result = page.getByRole('region', { name: 'DeCA generado' })
  await expect(result).toBeVisible()
  await expect(result.getByText('Válido como DeCA')).toBeVisible()
  const qr = result.getByRole('img', { name: /^Código QR del documento/ })
  await expect(qr).toBeVisible()
  expect(await qr.evaluate((element) => element.tagName)).toBe('IMG')
  expect(await qr.getAttribute('src')).toMatch(/^blob:/)
  await expect(result.getByText(/\/v\/[\w-]+/)).toBeVisible()
  await expect(result.getByRole('button', { name: 'Enviar a impresión' })).toBeVisible()
  await expect(result.getByRole('link', { name: 'Abrir en Documentos' })).toBeVisible()
  // El resultado queda a la vista: no se esconde debajo de un formulario largo.
  await expect
    .poll(async () => {
      const box = await result.boundingBox()
      const viewport = page.viewportSize()!
      return Boolean(box && box.y >= 0 && box.y < viewport.height)
    }, { message: 'el resultado entra en el viewport tras generar' })
    .toBe(true)
  await shots(page, '03-deca-generado')
})
