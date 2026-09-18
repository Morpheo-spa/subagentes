/**
 * Como se reparte el catalogo en bloques visibles.
 *
 * OJO: `GET /deca/fields` NO devuelve ningun grupo; lo unico que ordena es
 * `sort_order` (ver `DecaFieldRead` en `backend/app/schemas/deca.py`). Pero el
 * art. 6 exige identificar al cargador contractual y al transportista efectivo
 * "de forma expresa y diferenciada", asi que la UI tiene que separarlos si o si,
 * y `deca-form.md` pide ademas envio, mercancia y observaciones aparte.
 *
 * Solucion sin inventarse catalogo: cada bloque se reconoce por el prefijo del
 * `code`, igual que hace el backend en `deca.py` (`PARTY_PREFIXES`), y TODO lo
 * demas cae en el bloque de envio, por `sort_order`. Asi un campo nuevo del
 * catalogo aparece siempre, aunque este front no sepa nada de el.
 */
import type { DecaFieldRead } from '@/lib/types'
import { PARTY_PREFIXES } from './deca-validation'

/** Bloques no-parte, tambien por prefijo del `code` (deca-form.md). */
const TOPIC_PREFIXES = ['mercancia', 'observaciones'] as const

export type DecaBlock =
  | (typeof PARTY_PREFIXES)[number]
  | 'envio'
  | (typeof TOPIC_PREFIXES)[number]

export const BLOCK_ORDER: DecaBlock[] = [...PARTY_PREFIXES, 'envio', ...TOPIC_PREFIXES]

/** El bloque de un campo, deducido de su `code`. */
export function blockOf(field: DecaFieldRead): DecaBlock {
  const party = PARTY_PREFIXES.find((prefix) => field.code.startsWith(`${prefix}_`))
  if (party) return party
  const topic = TOPIC_PREFIXES.find(
    (prefix) => field.code === prefix || field.code.startsWith(`${prefix}_`),
  )
  return topic ?? 'envio'
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
