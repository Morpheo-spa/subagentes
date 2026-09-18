/**
 * Validador del formulario DeCA.
 *
 * Las definiciones de campo vienen de `GET /api/v1/deca/fields`: aqui NO hay
 * ninguna lista de campos (`.claude/rules/deca.md`). Solo se implementan los
 * tipos de dato que el catalogo puede declarar.
 *
 * El backend vuelve a validar siempre; esto es para el error inline al blur.
 */
import type { DecaFieldDefinition } from '@/lib/types'

export type DecaValues = Record<string, string>

export interface ValidationIssue {
  /** Clave i18n del mensaje. */
  key: string
  params?: Record<string, string | number>
}

export type DecaErrors = Record<string, ValidationIssue>

const NIF_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE'
const CIF_CONTROL = 'JABCDEFGHI'
const PLATE_PATTERNS = [
  /^\d{4}[BCDFGHJKLMNPRSTVWXYZ]{3}$/, // ES actual: 1234 BCD
  /^[A-Z]{1,2}\d{4}[A-Z]{1,2}$/, // ES anterior y varios formatos UE
]

/** NIF/NIE/CIF espanol con digito de control. */
export function isValidNif(raw: string): boolean {
  const value = raw.trim().toUpperCase().replace(/[\s-]/g, '')
  if (value.length !== 9) return false

  // NIF de persona fisica: 8 digitos + letra.
  if (/^\d{8}[A-Z]$/.test(value)) {
    return NIF_LETTERS[Number(value.slice(0, 8)) % 23] === value[8]
  }

  // NIE: X/Y/Z + 7 digitos + letra.
  if (/^[XYZ]\d{7}[A-Z]$/.test(value)) {
    const prefix = String('XYZ'.indexOf(value[0]))
    return NIF_LETTERS[Number(prefix + value.slice(1, 8)) % 23] === value[8]
  }

  // CIF de persona juridica: letra + 7 digitos + control (digito o letra).
  if (/^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$/.test(value)) {
    const digits = value.slice(1, 8)
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
    const expectedDigit = String(control)
    const expectedLetter = CIF_CONTROL[control]
    const provided = value[8]
    return provided === expectedDigit || provided === expectedLetter
  }

  return false
}

export function isValidPlate(raw: string): boolean {
  const value = raw.trim().toUpperCase().replace(/[\s-]/g, '')
  return PLATE_PATTERNS.some((pattern) => pattern.test(value))
}

/** Valida un campo. `null` = sin problema. */
export function validateField(
  field: DecaFieldDefinition,
  rawValue: string | undefined,
): ValidationIssue | null {
  const value = (rawValue ?? '').trim()

  if (!value) {
    return field.required ? { key: 'deca.validation.required' } : null
  }

  if (field.max_length && value.length > field.max_length) {
    return { key: 'deca.validation.maxLength', params: { max: field.max_length } }
  }

  if (field.pattern) {
    let pattern: RegExp | null = null
    try {
      pattern = new RegExp(field.pattern)
    } catch {
      pattern = null // patron invalido en el catalogo: lo valida el backend
    }
    if (pattern && !pattern.test(value)) return { key: 'deca.validation.pattern' }
  }

  switch (field.type) {
    case 'number': {
      const parsed = Number(value.replace(',', '.'))
      if (!Number.isFinite(parsed)) return { key: 'deca.validation.number' }
      if (field.min !== null && parsed < field.min) {
        return { key: 'deca.validation.min', params: { min: field.min } }
      }
      if (field.max !== null && parsed > field.max) {
        return { key: 'deca.validation.max', params: { max: field.max } }
      }
      return null
    }
    case 'date': {
      const parsed = new Date(value)
      if (Number.isNaN(parsed.getTime())) return { key: 'deca.validation.date' }
      return null
    }
    case 'nif':
      return isValidNif(value) ? null : { key: 'deca.validation.nif' }
    case 'plate':
      return isValidPlate(value) ? null : { key: 'deca.validation.plate' }
    case 'select': {
      const options = field.options ?? []
      if (options.length && !options.some((option) => option.value === value)) {
        return { key: 'deca.validation.option' }
      }
      return null
    }
    default:
      return null
  }
}

export function validateAll(fields: DecaFieldDefinition[], values: DecaValues): DecaErrors {
  const errors: DecaErrors = {}
  for (const field of fields) {
    const issue = validateField(field, values[field.code])
    if (issue) errors[field.code] = issue
  }
  return errors
}

/**
 * Requisito transversal de docs/DECA.md §3: cargador contractual y
 * transportista efectivo van en bloques separados y etiquetados.
 */
export const GROUP_ORDER = ['cargador', 'transportista', 'envio', 'mercancia', 'otros'] as const

export function groupFields(fields: DecaFieldDefinition[]) {
  const sorted = [...fields].sort((a, b) => a.order - b.order)
  return GROUP_ORDER.map((group) => ({
    group,
    fields: sorted.filter((field) => field.group === group),
  })).filter((entry) => entry.fields.length > 0)
}
