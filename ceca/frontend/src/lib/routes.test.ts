import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { declaredRoutes } from './routes'

/**
 * Que cada ruta exista en el backend con ese metodo lo comprueba
 * `contract.test.ts` contra el OpenAPI real (`openapi.snapshot.json`), no una
 * tabla transcrita a mano. Aqui quedan las reglas del registro en si.
 */

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
  })
}

describe('registro de rutas', () => {
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
