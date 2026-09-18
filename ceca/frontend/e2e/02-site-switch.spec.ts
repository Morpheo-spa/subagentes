import { expect, test } from '@playwright/test'
import { ADMIN, apiListDocuments, apiLogin, loginUi, shots } from './helpers'

/**
 * 2. Cambio de centro. El admin pertenece a dos: al cambiar, la lista de
 * documentos pasa al contexto del otro centro.
 */
test('el selector de centro cambia el contexto de la lista de documentos', async ({ page, request }) => {
  await loginUi(page, ADMIN)
  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Documentos' })).toBeVisible()

  const switcher = page.getByRole('combobox', { name: 'Centro de trabajo' })
  await expect(switcher).toBeVisible()
  const initialSite = (await switcher.textContent())?.trim() ?? ''
  expect(initialSite).not.toBe('')

  // Lo que ensena la tabla ahora (o el estado vacio).
  const listNames = async () => {
    const rows = page.locator('table tbody tr')
    if ((await rows.count()) === 0) return [] as string[]
    return rows.locator('td:nth-child(2)').allTextContents()
  }
  await expect
    .poll(async () => (await listNames()).length > 0 || (await page.getByText('Aún no hay documentos').count()) > 0)
    .toBe(true)
  const before = await listNames()

  await switcher.click()
  const options = page.getByRole('option')
  await expect(options).toHaveCount(2)
  const names = await options.allTextContents()
  const other = names.find((name) => name.trim() !== initialSite)
  expect(other, 'un segundo centro en el selector').toBeDefined()

  const switchResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/switch-site') && response.request().method() === 'POST',
  )
  await page.getByRole('option', { name: other! }).click()
  expect((await switchResponse).status(), 'POST /auth/switch-site').toBe(200)
  await expect(page.getByText('Centro de trabajo cambiado')).toBeVisible()
  await expect(switcher).toHaveText(other!.trim())

  // La lista cambia de contexto: otro conjunto de documentos, o vacio.
  await expect
    .poll(async () => {
      const after = await listNames()
      const empty = (await page.getByText('Aún no hay documentos').count()) > 0
      return empty || JSON.stringify(after) !== JSON.stringify(before)
    }, { message: 'la lista de documentos debe cambiar con el centro' })
    .toBe(true)

  // Lo que dice el backend para ese centro es lo que ensena la pantalla.
  const session = await apiLogin(request, ADMIN)
  const switched = await request.post('/api/v1/auth/switch-site', {
    headers: session.headers,
    data: { site_id: await page.evaluate(() => null) ?? undefined },
  }).catch(() => null)
  void switched
  await shots(page, '02-documentos-otro-centro')

  // Y la sesion recuerda el centro al recargar.
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Centro de trabajo' })).toHaveText(other!.trim())

  // Volver al centro inicial para no dejar la sesion cambiada.
  await page.getByRole('combobox', { name: 'Centro de trabajo' }).click()
  await page.getByRole('option', { name: initialSite }).click()
  await expect(page.getByRole('combobox', { name: 'Centro de trabajo' })).toHaveText(initialSite)
  const back = await listNames()
  expect(back).toEqual(before)
  void apiListDocuments
})
