import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

/**
 * Suite de extremo a extremo contra el stack REAL (Vite + FastAPI + Postgres +
 * Redis), ya levantado: aqui no se arranca ni se para nada.
 *
 * Siempre `127.0.0.1`, nunca `localhost`: el backend valida `Origin` contra
 * `PUBLIC_BASE_URL` y con `localhost` el refresh de sesion responde 403.
 */
export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'

// Chromium preinstalado. Si el `@playwright/test` del proyecto espera otra
// revision, se lanza el binario del sistema por ruta.
const SYSTEM_CHROMIUM = process.env.E2E_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'
const executablePath = existsSync(SYSTEM_CHROMIUM) ? SYSTEM_CHROMIUM : undefined

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  outputDir: './test-results',
  // Los tests comparten backend (cola de impresion, documentos): en serie.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    locale: 'es-ES',
    timezoneId: 'Europe/Madrid',
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [{ name: 'chromium' }],
})
