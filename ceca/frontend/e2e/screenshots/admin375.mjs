import { chromium } from '@playwright/test'
const BASE = 'http://127.0.0.1:5173'
const browser = await chromium.launch({ executablePath: process.env.E2E_CHROMIUM_PATH || '/opt/pw-browsers/chromium' })
const context = await browser.newContext({ viewport: { width: 375, height: 812 }, locale: 'es-ES' })
const page = await context.newPage()
await page.goto(`${BASE}/login`)
await page.getByLabel('Correo electrónico').fill('admin@estampa-demo.com')
await page.getByLabel('Contraseña').fill('estampa-demo-2026')
await page.getByRole('button', { name: 'Entrar' }).click()
await page.waitForURL(/\/upload$/)
await page.goto(`${BASE}/admin`); await page.getByRole('tab', { name: 'Usuarios y roles' }).click(); await page.waitForTimeout(600)
await page.screenshot({ path: '/tmp/claude-0/-home-user-subagentes/0a494a2f-187a-5b4f-b97c-7bd52851a89c/scratchpad/shots/admin-users-375.png', fullPage: false })
await browser.close()
