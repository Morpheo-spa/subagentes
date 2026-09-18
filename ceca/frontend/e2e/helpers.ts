import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url))

/* ---- Cuentas de demo ------------------------------------------------- */

export interface DemoUser {
  email: string
  password: string
}

const PASSWORD = 'estampa-demo-2026'
export const ADMIN: DemoUser = { email: 'admin@estampa-demo.com', password: PASSWORD }
export const OPERATOR: DemoUser = { email: 'operador@estampa-demo.com', password: PASSWORD }
export const VIEWER: DemoUser = { email: 'viewer@estampa-demo.com', password: PASSWORD }

/* ---- Datos DeCA validos (NIF/CIF con digito de control real) ----------- */

export const VALID_CARGADOR_NIF = 'B12345674'
export const VALID_TRANSPORTISTA_NIF = 'A58818501'
/** Mismo formato, digito de control incorrecto. */
export const INVALID_NIF = 'B12345670'

export const DECA_VALUES: Record<string, string> = {
  cargador_nombre: 'Cargas del Norte SL',
  cargador_nif: VALID_CARGADOR_NIF,
  cargador_domicilio: 'Polígono Sur 12, Zaragoza',
  transportista_nombre: 'Transportes Ebro SA',
  transportista_nif: VALID_TRANSPORTISTA_NIF,
  origen: 'Zaragoza',
  destino: 'Bilbao',
  mercancia_naturaleza: 'Bobinas de papel',
  mercancia_peso: '18.5',
  mercancia_peso_unidad: 't',
  fecha_transporte: '2026-10-06',
  matricula_vehiculo: '1234 KLM',
}

/* ---- Capturas ---------------------------------------------------------- */

export const WIDTHS = [375, 768, 1024, 1440] as const
export const SCREENSHOT_DIR = path.resolve(E2E_DIR, 'screenshots')

/**
 * Captura la pantalla actual en los cuatro anchos de MASTER §5 y deja el
 * viewport como estaba.
 */
export async function shots(page: Page, name: string, options: { fullPage?: boolean } = {}) {
  mkdirSync(SCREENSHOT_DIR, { recursive: true })
  const original = page.viewportSize() ?? { width: 1440, height: 900 }
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 900 })
    await page.waitForTimeout(250)
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `${name}-${width}.png`),
      fullPage: options.fullPage ?? true,
    })
  }
  await page.setViewportSize(original)
  await page.waitForTimeout(150)
}

/** Espera a que terminen las animaciones en curso (sheet, filas, toasts). */
export async function settle(page: Page) {
  await page
    .evaluate(() =>
      Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))),
    )
    .catch(() => undefined)
  await page.waitForTimeout(100)
}

/** Una sola captura al ancho actual (para estados intermedios). */
export async function shot(page: Page, name: string) {
  mkdirSync(SCREENSHOT_DIR, { recursive: true })
  const width = page.viewportSize()?.width ?? 0
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}-${width}.png`), fullPage: true })
}

/** `scrollWidth <= innerWidth`: sin scroll horizontal (MASTER §12). */
export async function horizontalOverflow(page: Page): Promise<{ scrollWidth: number; innerWidth: number }> {
  return page.evaluate(() => ({
    scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    innerWidth: window.innerWidth,
  }))
}

/* ---- Sesion por la interfaz ------------------------------------------- */

export async function loginUi(page: Page, user: DemoUser, landing: RegExp = /\/upload$/) {
  await page.goto('/login')
  await page.getByLabel('Correo electrónico').fill(user.email)
  await page.getByLabel('Contraseña').fill(user.password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL(landing)
}

export async function logoutUi(page: Page) {
  await page.getByRole('button', { name: /Adrián|Admin|Operador|Viewer|Visor|@/i }).first().click()
  await page.getByRole('menuitem', { name: 'Cerrar sesión' }).click()
  await expect(page).toHaveURL(/\/login$/)
}

/* ---- API directa (preparar datos, comprobar efectos) ------------------ */

export interface ApiSession {
  token: string
  headers: Record<string, string>
  siteId: string
  siteName: string
  userId: string
}

/**
 * Login por API. Usa el mismo `request` del contexto del navegador, asi que
 * la cookie de refresh que deja el backend se comparte con la pagina.
 */
export async function apiLogin(request: APIRequestContext, user: DemoUser): Promise<ApiSession> {
  const response = await request.post('/api/v1/auth/login', {
    data: { email: user.email, password: user.password },
    headers: { 'Accept-Language': 'es' },
  })
  expect(response.status(), `login API ${user.email}`).toBe(200)
  const body = await response.json()
  const token = body.tokens.access_token as string
  return {
    token,
    headers: { Authorization: `Bearer ${token}`, 'Accept-Language': 'es' },
    siteId: body.site.id,
    siteName: body.site.name,
    userId: body.user.id,
  }
}

export interface ApiDocument {
  id: string
  original_filename: string
  status: string
  origin: string
  compliance_status: string
  is_valid_deca: boolean
  revision: number
  withdrawn_at: string | null
  superseded_at: string | null
  public_url?: string | null
  share_token?: string | null
  deca?: Record<string, unknown>
}

export async function apiListDocuments(
  request: APIRequestContext,
  session: ApiSession,
  query: Record<string, string> = {},
): Promise<{ items: ApiDocument[]; total: number }> {
  const params = new URLSearchParams({ page: '1', page_size: '50', ...query })
  const response = await request.get(`/api/v1/documents/?${params}`, { headers: session.headers })
  expect(response.status(), 'GET /documents/').toBe(200)
  return response.json()
}

export async function apiGetDocument(
  request: APIRequestContext,
  session: ApiSession,
  id: string,
): Promise<ApiDocument> {
  const response = await request.get(`/api/v1/documents/${id}`, { headers: session.headers })
  expect(response.status(), `GET /documents/${id}`).toBe(200)
  return response.json()
}

export interface GenerateResult {
  ok: boolean
  status: number
  document: ApiDocument | null
  body: unknown
}

/** `POST /documents/generate`. No falla el test: devuelve el resultado crudo. */
export async function apiGenerate(
  request: APIRequestContext,
  session: ApiSession,
  values: Record<string, string> = DECA_VALUES,
): Promise<GenerateResult> {
  const response = await request.post('/api/v1/documents/generate', {
    data: { deca: values },
    headers: session.headers,
  })
  const body: unknown = await response.json().catch(() => null)
  const ok = response.status() === 201 || response.status() === 200
  return { ok, status: response.status(), document: ok ? (body as ApiDocument) : null, body }
}

export async function apiUpload(
  request: APIRequestContext,
  session: ApiSession,
  name: string,
  buffer: Buffer,
): Promise<{ document: ApiDocument | null; warnings: { code: string }[]; error: unknown }> {
  const response = await request.post('/api/v1/documents/', {
    headers: session.headers,
    multipart: { files: { name, mimeType: 'application/pdf', buffer } },
  })
  expect(response.status(), 'POST /documents/').toBe(201)
  const body = await response.json()
  const item = body.items[0]
  return { document: item.document, warnings: item.warnings, error: item.error }
}

export async function apiDownloadFile(
  request: APIRequestContext,
  session: ApiSession,
  id: string,
): Promise<Buffer> {
  const response = await request.get(`/api/v1/documents/${id}/file`, { headers: session.headers })
  expect(response.status(), `GET /documents/${id}/file`).toBe(200)
  return response.body()
}

export async function apiClearQueue(request: APIRequestContext, session: ApiSession) {
  const response = await request.delete('/api/v1/printing/queue/', { headers: session.headers })
  expect([200, 204]).toContain(response.status())
}

/**
 * Un documento "listo" y vigente sobre el que trabajar. Prefiere uno recien
 * generado (PDF nativo con QR); si `generate` no responde, cae a una subida
 * nativa hecha por API. Devuelve tambien de donde salio, para el informe.
 */
export async function ensureLiveDocument(
  request: APIRequestContext,
  session: ApiSession,
): Promise<{ document: ApiDocument; source: 'generated' | 'uploaded' }> {
  const generated = await apiGenerate(request, session)
  if (generated.document) {
    return { document: await apiGetDocument(request, session, generated.document.id), source: 'generated' }
  }
  const uploaded = await apiUpload(request, session, `e2e-nativo-${Date.now()}.pdf`, nativePdf())
  expect(uploaded.document, 'subida nativa por API').not.toBeNull()
  return {
    document: await apiGetDocument(request, session, uploaded.document!.id),
    source: 'uploaded',
  }
}

/* ---- PDFs de prueba ----------------------------------------------------- */

/** Ensambla un PDF minimo con tabla xref correcta. */
function buildPdf(objects: string[]): Buffer {
  let out = '%PDF-1.4\n%âãÏÓ\n'
  const offsets: number[] = []
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(out, 'latin1'))
    out += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xref = Buffer.byteLength(out, 'latin1')
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const offset of offsets) out += `${String(offset).padStart(10, '0')} 00000 n \n`
  out += `trailer<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

/**
 * "Escaneo": una pagina vacia, sin capa de texto. `salt` cambia el fichero
 * para que cada ejecucion no choque por hash con la anterior.
 */
export function scanPdf(salt: string = String(Date.now())): Buffer {
  return buildPdf([
    '<</Type/Catalog/Pages 2 0 R>>',
    '<</Type/Pages/Kids[3 0 R]/Count 1>>',
    `<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/E2E(${salt})>>`,
  ])
}

/** PDF nativo: texto real con Helvetica (fuente estandar, extraible). */
export function nativePdf(text: string = `Albaran e2e nativo ${Date.now()}`): Buffer {
  const content = `BT /F1 12 Tf 72 760 Td (${text.replace(/[()\\]/g, '')}) Tj ET`
  return buildPdf([
    '<</Type/Catalog/Pages 2 0 R>>',
    '<</Type/Pages/Kids[3 0 R]/Count 1>>',
    '<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>',
    '<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>',
    `<</Length ${content.length}>>stream\n${content}\nendstream`,
  ])
}

/* ---- Almacenamiento del navegador --------------------------------------- */

export interface StorageDump {
  local: Record<string, string>
  session: Record<string, string>
}

export async function dumpStorage(page: Page): Promise<StorageDump> {
  return page.evaluate(() => {
    const read = (storage: Storage) => {
      const out: Record<string, string> = {}
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index)
        if (key) out[key] = storage.getItem(key) ?? ''
      }
      return out
    }
    return { local: read(window.localStorage), session: read(window.sessionStorage) }
  })
}

/** Cabecera.payload.firma en base64url: lo que un JWT parece siempre. */
export const JWT_RE = /eyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]{4,}/

/* ---- Tema ---------------------------------------------------------------- */

export async function useDarkTheme(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('estampa.theme', 'dark')
    } catch {
      /* sin storage */
    }
  })
}

/** Convierte la URL publica que devuelve el backend a la del servidor de la SPA. */
export function toSpaUrl(publicUrl: string, baseURL: string): string {
  const target = new URL(publicUrl)
  const base = new URL(baseURL)
  target.protocol = base.protocol
  target.host = base.host
  return target.toString()
}
