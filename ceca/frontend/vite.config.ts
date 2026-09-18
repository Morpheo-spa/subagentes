/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * Solo desarrollo: a donde reenvia Vite `/api` y `/v`.
 *
 * El proxy es obligatorio, no una comodidad. `POST /auth/refresh` lee la cookie
 * HttpOnly `estampa_refresh` (`SameSite=strict`, `Path=/api/v1/auth`) y rechaza
 * con 403 `CROSS_ORIGIN_REJECTED` cualquier `Origin` distinto de su
 * `PUBLIC_BASE_URL`. Con el proxy, el navegador solo ve un origen (el de Vite),
 * la cookie viaja, y el `Origin` que recibe el backend es el de Vite: por eso
 * en desarrollo `PUBLIC_BASE_URL` del backend apunta a la URL de Vite.
 * `changeOrigin` reescribe `Host`, no `Origin`.
 */
const DEV_API_PROXY = process.env.VITE_DEV_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: DEV_API_PROXY,
        changeOrigin: true,
      },
      // El visor publico comparte prefijo con la pagina de la SPA (`/v/:token`):
      // una navegacion del navegador (Accept: text/html) la sirve Vite; el JSON
      // y el PDF que pide esa pagina van al backend.
      '/v': {
        target: DEV_API_PROXY,
        changeOrigin: true,
        bypass: (req) => (req.headers.accept?.includes('text/html') ? req.url : undefined),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
