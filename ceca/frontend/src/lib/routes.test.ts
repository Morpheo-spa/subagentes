import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { declaredRoutes, type RouteBase } from './routes'

/**
 * La tabla de `backend/app/routers/`, transcrita.
 *
 * Si el backend anade, quita o mueve una ruta, este fichero se actualiza a mano
 * y el test dira que rutas del cliente se han quedado sin destino. Es a
 * proposito: que la desincronizacion salte aqui y no en produccion.
 */
const BACKEND_ROUTES: Record<RouteBase, string[]> = {
  api: [
    'POST /auth/login',
    'POST /auth/refresh',
    'POST /auth/logout',
    'POST /auth/switch-site',
    'GET /auth/me',

    'GET /documents/',
    'POST /documents/',
    'POST /documents/generate',
    'GET /documents/export.csv',
    'GET /documents/{}',
    'GET /documents/{}/file',
    'GET /documents/{}/history',
    'GET /documents/{}/qr.png',
    'GET /documents/{}/qr.svg',
    'PATCH /documents/{}/deca',
    'POST /documents/{}/revisions',
    'POST /documents/{}/share/revoke',
    'POST /documents/{}/withdraw',

    'GET /deca/fields',
    'POST /deca/validate',

    'GET /printing/queue/',
    'POST /printing/queue/',
    'DELETE /printing/queue/',
    'DELETE /printing/queue/{}',
    'POST /printing/queue/reorder',
    'GET /printing/templates',
    'GET /printing/jobs/',
    'POST /printing/jobs/',
    'GET /printing/jobs/{}/render',
    'POST /printing/jobs/{}/confirm',

    'GET /storage/',
    'POST /storage/',
    'GET /storage/{}',
    'PATCH /storage/{}',
    'DELETE /storage/{}',
    'POST /storage/{}/test',

    'GET /retention/',
    'POST /retention/',
    'GET /retention/upcoming',
    'GET /retention/{}',
    'PATCH /retention/{}',
    'DELETE /retention/{}',

    'GET /sites/',
    'POST /sites/',
    'GET /sites/{}',
    'PATCH /sites/{}',
    'DELETE /sites/{}',

    'GET /users/',
    'POST /users/',
    'GET /users/roles',
    'GET /users/{}',
    'PATCH /users/{}',

    'GET /billing/plans',
    'GET /billing/subscription',
    'GET /billing/usage',
    'POST /billing/checkout',
    'POST /billing/portal',
  ],
  // El visor publico se monta sin `api_prefix`.
  root: ['GET /v/{}', 'HEAD /v/{}', 'GET /v/{}/file'],
}

/** `/documents/{documentId}` y `/documents/{id}` son la misma ruta. */
function normalize(method: string, template: string): string {
  return `${method} ${template.replace(/\{\w+\}/g, '{}')}`
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
  })
}

describe('contrato de rutas con el backend', () => {
  it('toda ruta que usa el cliente existe en el backend', () => {
    const missing = declaredRoutes()
      .map((route) => ({ ...route, signature: normalize(route.method, route.template) }))
      .filter((route) => !BACKEND_ROUTES[route.base].includes(route.signature))
      .map((route) => `${route.signature} (base ${route.base})`)

    expect(missing).toEqual([])
  })

  it('el visor publico no cuelga de /api/v1', () => {
    const publicRoutes = declaredRoutes().filter((route) => route.template.startsWith('/v/'))
    expect(publicRoutes.length).toBeGreaterThan(0)
    for (const route of publicRoutes) expect(route.base).toBe('root')
  })

  it('ningun modulo arma una ruta de API a mano fuera del registro', () => {
    // `request`, `api.*` y `upload` solo aceptan un `ApiRoute`, asi que una ruta
    // escrita a mano ni compila. Esto cubre el otro portillo: `fetch` directo.
    const offenders = sourceFiles(join(process.cwd(), 'src'))
      .filter((file) => !file.endsWith(join('lib', 'api.ts')))
      .filter((file) => /(?<![.\w])fetch\s*\(/.test(readFileSync(file, 'utf8')))
      .map((file) => file.replace(process.cwd(), ''))

    expect(offenders).toEqual([])
  })
})
