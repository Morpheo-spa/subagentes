import { expect, test } from '@playwright/test'
import { ADMIN, apiLogin, loginUi, shots } from './helpers'

/**
 * 2. Cambio de centro. El admin pertenece a dos: al cambiar, la lista de
 * documentos pasa al contexto del otro centro y coincide con lo que el
 * backend devuelve para ese centro.
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
  const isEmpty = async () => (await page.getByText('Aún no hay documentos').count()) > 0
  await expect.poll(async () => (await listNames()).length > 0 || (await isEmpty())).toBe(true)
  const before = await listNames()

  await switcher.click()
  const options = page.getByRole('option')
  await expect(options).toHaveCount(2)
  const names = (await options.allTextContents()).map((name) => name.trim())
  const other = names.find((name) => name !== initialSite)
  expect(other, 'un segundo centro en el selector').toBeDefined()

  const switchResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/auth/switch-site') && response.request().method() === 'POST',
  )
  await page.getByRole('option', { name: other! }).click()
  expect((await switchResponse).status(), 'POST /auth/switch-site').toBe(200)
  await expect(page.getByText('Centro de trabajo cambiado')).toBeVisible()
  await expect(switcher).toHaveText(other!)

  // La lista cambia de contexto: otro conjunto de documentos, o vacio.
  await expect
    .poll(
      async () => (await isEmpty()) || JSON.stringify(await listNames()) !== JSON.stringify(before),
      { message: 'la lista de documentos debe cambiar con el centro' },
    )
    .toBe(true)
  const after = await listNames()

  // Contraste con el backend: el total del otro centro es lo que se ve.
  const session = await apiLogin(request, ADMIN)
  const me = await (await request.get('/api/v1/auth/me', { headers: session.headers })).json()
  const otherSite = (me.sites as { site: { id: string; name: string } }[]).find(
    (membership) => membership.site.name === other,
  )
  expect(otherSite, 'el otro centro existe en /auth/me').toBeDefined()
  const switched = await request.post('/api/v1/auth/switch-site', {
    headers: { ...session.headers, Origin: new URL(page.url()).origin },
    data: { site_id: otherSite!.site.id },
  })
  expect(switched.status()).toBe(200)
  const otherToken = (await switched.json()).tokens.access_token as string
  const otherList = await (
    await request.get('/api/v1/documents/?page=1&page_size=50', {
      headers: { Authorization: `Bearer ${otherToken}` },
    })
  ).json()
  expect(after.length).toBe(Math.min(otherList.total as number, 25))

  await shots(page, '02-documentos-otro-centro')

  // La sesion recuerda el centro al recargar.
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Centro de trabajo' })).toHaveText(other!)

  // Volver al centro inicial para no dejar la sesion cambiada.
  await page.getByRole('combobox', { name: 'Centro de trabajo' }).click()
  await page.getByRole('option', { name: initialSite }).click()
  await expect(page.getByRole('combobox', { name: 'Centro de trabajo' })).toHaveText(initialSite)
  await expect.poll(async () => JSON.stringify(await listNames())).toBe(JSON.stringify(before))
})
