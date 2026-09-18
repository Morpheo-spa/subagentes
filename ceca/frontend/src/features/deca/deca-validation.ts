/**
 * Validador del formulario DeCA, espejo de `app/services/deca.py`.
 *
 * Las definiciones vienen de `GET /api/v1/deca/fields`: aqui NO hay ninguna
 * lista de campos. Solo se implementan los `data_type` que el catalogo declara
 * (`DecaFieldType` en `app/models/deca.py`).
 *
 * El backend vuelve a validar siempre (`POST /deca/validate` y al guardar);
 * esto es para el error inline al blur, sin ida y vuelta.
 */
import type { DecaFieldRead } from '@/lib/types'

export type DecaValues = Record<string, string>

export interface ValidationIssue {
  /** Clave i18n del mensaje. */
  key: string
  params?: Record<string, string | number>
}

export type DecaErrors = Record<string, ValidationIssue>

/**
 * Igual que el backend: el NIF se reconoce por el sufijo del `code`, no por una
 * lista de campos. Un campo nuevo `xxx_nif` en el catalogo se valida solo.
 */
export const TAX_ID_SUFFIX = '_nif'

const NIF_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE'
const CIF_CONTROL_LETTERS = 'JABCDEFGHI'
const NIE_PREFIXES: Record<string, string> = { X: '0', Y: '1', Z: '2' }

const NIF_RE = /^\d{8}[A-Z]$/
const NIE_RE = /^[XYZ]\d{7}[A-Z]$/
const CIF_RE = /^[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]$/
const SEPARATORS = /[\s.-]/g

function normalizeTaxId(value: string): string {
  return value.replace(SEPARATORS, '').toUpperCase()
}

function nifControl(digits: string): string {
  return NIF_LETTERS[Number(digits) % 23]
}

function cifIsValid(candidate: string): boolean {
  const digits = candidate.slice(1, 8)
  let sum = 0
  for (let index = 0; index < digits.length; index += 1) {
    const digit = Number(digits[index])
    // Posiciones impares (1-based) se duplican y se suman sus cifras.
    if (index % 2 === 0) {
      const doubled = digit * 2
      sum += Math.floor(doubled / 10) + (doubled % 10)
    } else {
      sum += digit
    }
  }
  const control = (10 - (sum % 10)) % 10
  const provided = candidate[8]
  return provided === String(control) || provided === CIF_CONTROL_LETTERS[control]
}

/** NIF, NIE o CIF, con su digito de control real (no una regex de longitud). */
export function isValidTaxId(value: string): boolean {
  const candidate = normalizeTaxId(value)
  if (NIF_RE.test(candidate)) return candidate[8] === nifControl(candidate.slice(0, 8))
  if (NIE_RE.test(candidate)) {
    return candidate[8] === nifControl(NIE_PREFIXES[candidate[0]] + candidate.slice(1, 8))
  }
  if (CIF_RE.test(candidate)) return cifIsValid(candidate)
  return false
}

function isPositiveNumber(value: string): boolean {
  const parsed = Number(value.replace(',', '.'))
  return Number.isFinite(parsed) && parsed > 0
}

function isDate(value: string): boolean {
  return !Number.isNaN(new Date(value).getTime())
}

function matchesType(field: DecaFieldRead, value: string): boolean {
  switch (field.data_type) {
    case 'number':
    case 'decimal':
      return isPositiveNumber(value)
    case 'date':
    case 'datetime':
      return isDate(value)
    case 'boolean':
      return ['true', 'false', '1', '0'].includes(value.toLowerCase())
    case 'enum':
      return field.choices.includes(value)
    default:
      return true
  }
}

function matchesShape(field: DecaFieldRead, value: string): boolean {
  if (!field.pattern) return true
  try {
    return new RegExp(field.pattern).test(value)
  } catch {
    return true // patron invalido en el catalogo: que lo diga el backend
  }
}

/** Valida un campo. `null` = sin problema. */
export function validateField(
  field: DecaFieldRead,
  rawValue: string | undefined,
): ValidationIssue | null {
  const value = (rawValue ?? '').trim()

  if (!value) return field.is_required ? { key: 'deca.validation.required' } : null

  if (!matchesType(field, value)) return { key: `deca.validation.type.${field.data_type}` }

  if (field.max_length !== null && value.length > field.max_length) {
    return { key: 'deca.validation.maxLength', params: { max: field.max_length } }
  }
  if (!matchesShape(field, value)) return { key: 'deca.validation.pattern' }

  if (field.code.endsWith(TAX_ID_SUFFIX) && !isValidTaxId(value)) {
    return { key: 'deca.validation.nif' }
  }

  return null
}

export function validateAll(fields: DecaFieldRead[], values: DecaValues): DecaErrors {
  const errors: DecaErrors = {}
  for (const field of fields) {
    const issue = validateField(field, values[field.code])
    if (issue) errors[field.code] = issue
  }
  return errors
}

/**
 * Art. 6: cargador contractual y transportista efectivo van identificados de
 * forma expresa y diferenciada. El backend lo comprueba con
 * `DECA_PARTIES_NOT_DISTINCT`; aqui se avisa antes de gastar una peticion.
 */
export const PARTY_PREFIXES = ['cargador', 'transportista'] as const

export function partiesAreDistinct(fields: DecaFieldRead[], values: DecaValues): boolean {
  const taxIds = PARTY_PREFIXES.map((prefix) => {
    const field = fields.find(
      (entry) => entry.code.startsWith(prefix) && entry.code.endsWith(TAX_ID_SUFFIX),
    )
    return field ? normalizeTaxId(values[field.code] ?? '') : ''
  }).filter(Boolean)

  if (taxIds.length < PARTY_PREFIXES.length) return true
  return new Set(taxIds).size > 1
}
