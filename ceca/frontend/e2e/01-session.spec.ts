import { expect, test } from '@playwright/test'
import { ADMIN, dumpStorage, JWT_RE, loginUi, logoutUi, shots } from './helpers'

/**
 * 1. Login y sesion persistente.
 * El access token vive en memoria; el refresh en una cookie HttpOnly. Recargar
 * mantiene la sesion y nada parecido a un token toca localStorage/sessionStorage.
 */
test('login, recarga con sesion viva, sin tokens en storage, logout', async ({ page, context }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Entrar en Estampa' })).toBeVisible()
  await shots(page, '01-login')

  await loginUi(page, ADMIN)
  await expect(page.getByRole('heading', { name: 'Subir PDFs' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Navegación principal' })).toBeVisible()

  // La cookie de refresh existe y el navegador no la expone a JS.
  const cookies = await context.cookies()
  const refresh = cookies.find((cookie) => cookie.name === 'estampa_refresh')
  expect(refresh, 'cookie estampa_refresh').toBeDefined()
  expect(refresh?.httpOnly, 'estampa_refresh es HttpOnly').toBe(true)
  expect(refresh?.path).toBe('/api/v1/auth')
  expect(refresh?.sameSite).toBe('Strict')

  // Recargar: `POST /auth/refresh` desde la cookie, sin pasar por login.
  const refreshResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/auth/refresh') && response.request().method() === 'POST',
  )
  await page.reload()
  expect((await refreshResponse).status(), 'POST /auth/refresh tras recargar').toBe(200)
  await expect(page).toHaveURL(/\/upload$/)
  await expect(page.getByRole('heading', { name: 'Subir PDFs' })).toBeVisible()
  await expect(page.getByLabel('Correo electrónico')).toHaveCount(0)

  // Nada con "token" en la clave ni un JWT en el valor.
  const storage = await dumpStorage(page)
  for (const [area, entries] of Object.entries(storage)) {
    for (const [key, value] of Object.entries(entries)) {
      expect(key, `${area}Storage clave "${key}"`).not.toMatch(/token/i)
      expect(value, `${area}Storage valor de "${key}"`).not.toMatch(JWT_RE)
      expect(value, `${area}Storage valor de "${key}"`).not.toMatch(/refresh_token|access_token/i)
    }
  }
  await shots(page, '01-upload-autenticado')

  // Cerrar sesion: el backend borra la cookie; recargar lleva a login.
  await logoutUi(page)
  await expect(page.getByRole('heading', { name: 'Entrar en Estampa' })).toBeVisible()
  await page.reload()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Entrar en Estampa' })).toBeVisible()
  const after = await context.cookies()
  expect(after.find((cookie) => cookie.name === 'estampa_refresh'), 'cookie tras logout').toBeUndefined()

  // Una ruta protegida sin sesion vuelve a login.
  await page.goto('/documents')
  await expect(page).toHaveURL(/\/login$/)
})
