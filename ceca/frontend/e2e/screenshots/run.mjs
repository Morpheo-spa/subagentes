import { chromium } from '@playwright/test'
import fs from 'node:fs'
const BASE = 'http://127.0.0.1:5173'
const OUT = '/tmp/claude-0/-home-user-subagentes/0a494a2f-187a-5b4f-b97c-7bd52851a89c/scratchpad/shots'
const browser = await chromium.launch({ executablePath: process.env.E2E_CHROMIUM_PATH || '/opt/pw-browsers/chromium' })
const pages = ['/upload', '/deca/new', '/documents', '/printing', '/billing', '/admin']
// a public token for the viewer
const api = await fetch(`${BASE}/api/v1/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json', origin: BASE }, body: JSON.stringify({ email: 'admin@estampa-demo.com', password: 'estampa-demo-2026' }) })
const session = await api.json()
const docs = await (await fetch(`${BASE}/api/v1/documents/?page_size=50`, { headers: { authorization: `Bearer ${session.tokens.access_token}` } })).json()
const ready = docs.items.find((d) => d.status === 'ready' && d.public_url) || docs.items.find((d) => d.public_url)
const viewer = ready?.public_url ? new URL(ready.public_url).pathname : null
console.log('viewer', viewer)
for (const scheme of ['light', 'dark']) {
  for (const width of [1440, 375]) {
    const context = await browser.newContext({ viewport: { width, height: width < 768 ? 812 : 900 }, colorScheme: scheme, locale: 'es-ES' })
    const page = await context.newPage()
    await page.goto(`${BASE}/login`)
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${OUT}/login-${scheme}-${width}.png`, fullPage: true })
    await page.getByLabel('Correo electrónico').fill('admin@estampa-demo.com')
    await page.getByLabel('Contraseña').fill('estampa-demo-2026')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await page.waitForURL(/\/upload$/)
    for (const path of pages) {
      await page.goto(`${BASE}${path}`)
      await page.waitForLoadState('networkidle').catch(() => {})
      await page.waitForTimeout(600)
      await page.screenshot({ path: `${OUT}/${path.replace(/\//g, '_').slice(1)}-${scheme}-${width}.png`, fullPage: true })
    }
    if (viewer) {
      await page.goto(`${BASE}${viewer}`)
      await page.waitForTimeout(1500)
      await page.screenshot({ path: `${OUT}/viewer-${scheme}-${width}.png`, fullPage: true })
    }
    await context.close()
  }
}
await browser.close()
console.log(fs.readdirSync(OUT).filter((f) => f.endsWith('.png')).length, 'screenshots')
