import { expect, test } from '@playwright/test'
import { ADMIN, apiLogin, DECA_VALUES, loginUi, nativePdf, shots, VIEWER } from './helpers'

/**
 * 7. Permisos. El viewer no ve subir ni generar; si fuerza la API recibe 403
 * con `PERMISSION_DENIED`. El admin, con la misma peticion, si puede.
 */
test('viewer: sin subir/generar en la interfaz; forzar la API responde 403 PERMISSION_DENIED', async ({
  page,
}) => {
  await loginUi(page, VIEWER, /\/(upload|documents)$/)
  test.info().annotations.push({ type: 'landing-viewer', description: page.url() })

  const nav = page.getByRole('navigation', { name: 'Navegación principal' })
  await expect(nav).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Documentos' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Subir PDFs' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Generar DeCA' })).toHaveCount(0)

  await page.goto('/documents')
  await expect(page.getByRole('heading', { name: 'Documentos' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Subir|Generar/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Subir|Generar/ })).toHaveCount(0)
  await shots(page, '07-viewer-documentos')

  // Rutas protegidas a mano: sin permiso, sin pantalla de subida ni formulario.
  await page.goto('/upload')
  await expect(page.getByRole('heading', { name: 'Sin permiso' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Seleccionar archivos' })).toHaveCount(0)
  await page.goto('/deca/new')
  await expect(page.getByRole('heading', { name: 'Sin permiso' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generar el PDF' })).toHaveCount(0)
  await shots(page, '07-viewer-sin-permiso')

  // Forzar `POST /documents/generate` con el token del viewer.
  const viewer = await apiLogin(page.request, VIEWER)
  const forced = await page.request.post('/api/v1/documents/generate', {
    headers: viewer.headers,
    data: { deca: DECA_VALUES },
  })
  expect(forced.status()).toBe(403)
  const body = await forced.json()
  expect(body.detail.code).toBe('PERMISSION_DENIED')
  expect(body.detail.params?.permission).toBe('documents:create')

  // Subir tampoco.
  const upload = await page.request.post('/api/v1/documents/', {
    headers: viewer.headers,
    multipart: { files: { name: 'x.pdf', mimeType: 'application/pdf', buffer: nativePdf('viewer') } },
  })
  expect(upload.status()).toBe(403)
  expect((await upload.json()).detail.code).toBe('PERMISSION_DENIED')

  // Sin token: 401, no 403.
  const anonymous = await page.request.post('/api/v1/documents/generate', { data: { deca: {} } })
  expect(anonymous.status()).toBe(401)

  // Y leer si puede: la lista responde 200 con su token.
  const list = await page.request.get('/api/v1/documents/?page=1&page_size=1', { headers: viewer.headers })
  expect(list.status()).toBe(200)

  // Control: al admin no se le deniega el permiso (la peticion es la misma).
  const admin = await apiLogin(page.request, ADMIN)
  const allowed = await page.request.post('/api/v1/documents/generate', {
    headers: admin.headers,
    data: { deca: DECA_VALUES },
  })
  expect(allowed.status()).not.toBe(403)
})
