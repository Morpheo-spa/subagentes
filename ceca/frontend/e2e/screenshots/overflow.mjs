import { chromium } from '@playwright/test'
const BASE = 'http://127.0.0.1:5173'
const browser = await chromium.launch({ executablePath: process.env.E2E_CHROMIUM_PATH || '/opt/pw-browsers/chromium' })
const measure = (page) => page.evaluate(() => ({ sw: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), iw: window.innerWidth }))
const report = []
for (const width of [375, 768]) {
  const context = await browser.newContext({ viewport: { width, height: 812 }, locale: 'es-ES' })
  const page = await context.newPage()
  await page.goto(`${BASE}/login`)
  report.push([width, '/login', await measure(page)])
  await page.getByLabel('Correo electrónico').fill('admin@estampa-demo.com')
  await page.getByLabel('Contraseña').fill('estampa-demo-2026')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await page.waitForURL(/\/upload$/)
  for (const path of ['/upload', '/deca/new', '/documents', '/printing', '/billing']) {
    await page.goto(`${BASE}${path}`); await page.waitForLoadState('networkidle').catch(() => {}); await page.waitForTimeout(400)
    report.push([width, path, await measure(page)])
  }
  await page.goto(`${BASE}/admin`); await page.waitForLoadState('networkidle').catch(() => {})
  for (const tab of ['Centros', 'Usuarios y roles', 'Almacenamiento', 'Retención']) {
    await page.getByRole('tab', { name: tab }).click(); await page.waitForTimeout(500)
    report.push([width, `/admin#${tab}`, await measure(page)])
  }
  // sheet of the first document
  await page.goto(`${BASE}/documents`); await page.waitForLoadState('networkidle').catch(() => {}); await page.waitForTimeout(400)
  const first = page.locator('main').getByRole(width < 768 ? 'button' : 'row').filter({ hasText: /deca-/ }).first()
  await first.click().catch(() => {}); await page.waitForTimeout(600)
  report.push([width, '/documents#sheet', await measure(page)])
  await context.close()
}
await browser.close()
for (const [w, p, m] of report) console.log(`${w} ${p.padEnd(24)} scroll=${m.sw} inner=${m.iw} ${m.sw > m.iw ? 'OVERFLOW' : 'ok'}`)
