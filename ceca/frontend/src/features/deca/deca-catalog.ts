/**
 * Como se reparte el catalogo en bloques visibles.
 *
 * OJO: `GET /deca/fields` NO devuelve ningun grupo; lo unico que ordena es
 * `sort_order` (ver `DecaFieldRead` en `backend/app/schemas/deca.py`). Pero el
 * art. 6 exige identificar al cargador contractual y al transportista efectivo
 * "de forma expresa y diferenciada", asi que la UI tiene que separarlos si o si.
 *
 * Solucion sin inventarse catalogo: los dos bloques de partes se reconocen por
 * el prefijo del `code`, igual que hace el backend en `deca.py`
 * (`PARTY_PREFIXES`), y TODO lo demas cae en un unico bloque de envio, por
 * `sort_order`. Asi un campo nuevo del catalogo aparece siempre, aunque este
 * front no sepa nada de el.
 */
import type { DecaFieldRead } from '@/lib/types'
import { PARTY_PREFIXES } from './deca-validation'

export type DecaBlock = (typeof PARTY_PREFIXES)[number] | 'envio'

export const BLOCK_ORDER: DecaBlock[] = [...PARTY_PREFIXES, 'envio']

/** El bloque de un campo, deducido de su `code`. */
export function blockOf(field: DecaFieldRead): DecaBlock {
  const prefix = PARTY_PREFIXES.find((party) => field.code.startsWith(`${party}_`))
  return prefix ?? 'envio'
}

export interface DecaFieldBlock {
  block: DecaBlock
  fields: DecaFieldRead[]
}

/** Bloques en orden, sin bloques vacios. Dentro, por `sort_order`. */
export function groupFields(fields: DecaFieldRead[]): DecaFieldBlock[] {
  const sorted = [...fields].sort((a, b) => a.sort_order - b.sort_order)
  return BLOCK_ORDER.map((block) => ({
    block,
    fields: sorted.filter((field) => blockOf(field) === block),
  })).filter((entry) => entry.fields.length > 0)
}

/** Los obligatorios que siguen vacios: lo que deja el DeCA en `incompleto`. */
export function missingRequired(
  fields: DecaFieldRead[],
  values: Record<string, string>,
): DecaFieldRead[] {
  return fields.filter((field) => field.is_required && !(values[field.code] ?? '').trim())
}
