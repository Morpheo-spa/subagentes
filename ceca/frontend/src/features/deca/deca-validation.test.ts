import { describe, expect, it } from 'vitest'
import type { DecaFieldDefinition } from '@/lib/types'
import { groupFields, isValidNif, isValidPlate, validateAll, validateField } from './deca-validation'

function field(overrides: Partial<DecaFieldDefinition>): DecaFieldDefinition {
  return {
    code: 'campo',
    type: 'text',
    group: 'otros',
    required: false,
    order: 1,
    label_es: 'Campo',
    label_en: 'Field',
    help_es: null,
    help_en: null,
    pattern: null,
    min: null,
    max: null,
    max_length: null,
    options: null,
    legal_ref: null,
    ...overrides,
  }
}

describe('validador DeCA', () => {
  it('exige los campos marcados como required en el catalogo', () => {
    expect(validateField(field({ required: true }), '')).toEqual({ key: 'deca.validation.required' })
    expect(validateField(field({ required: true }), '   ')).toEqual({
      key: 'deca.validation.required',
    })
    expect(validateField(field({ required: false }), '')).toBeNull()
  })

  it('valida NIF, NIE y CIF por digito de control', () => {
    expect(isValidNif('12345678Z')).toBe(true)
    expect(isValidNif('12345678A')).toBe(false)
    expect(isValidNif('X1234567L')).toBe(true)
    expect(isValidNif('B12345674')).toBe(true)
    expect(isValidNif('B12345673')).toBe(false)
    expect(isValidNif('no-es-un-nif')).toBe(false)
  })

  it('valida matriculas espanolas con y sin separadores', () => {
    expect(isValidPlate('1234 BCD')).toBe(true)
    expect(isValidPlate('1234-BCD')).toBe(true)
    expect(isValidPlate('1234ABC')).toBe(false) // vocales no se usan
    expect(isValidPlate('M1234AB')).toBe(true)
    expect(isValidPlate('')).toBe(false)
  })

  it('aplica min, max y tipo numero', () => {
    const peso = field({ type: 'number', min: 0.001, max: 40000, required: true })
    expect(validateField(peso, '1200')).toBeNull()
    expect(validateField(peso, '1200,5')).toBeNull()
    expect(validateField(peso, '0')).toEqual({ key: 'deca.validation.min', params: { min: 0.001 } })
    expect(validateField(peso, '999999')).toEqual({
      key: 'deca.validation.max',
      params: { max: 40000 },
    })
    expect(validateField(peso, 'mucho')).toEqual({ key: 'deca.validation.number' })
  })

  it('respeta max_length, pattern y opciones del catalogo', () => {
    expect(validateField(field({ max_length: 3 }), 'abcd')).toEqual({
      key: 'deca.validation.maxLength',
      params: { max: 3 },
    })
    expect(validateField(field({ pattern: '^[A-Z]+$' }), 'abc')).toEqual({
      key: 'deca.validation.pattern',
    })
    const unidad = field({
      type: 'select',
      options: [
        { value: 'kg', label_es: 'kg', label_en: 'kg' },
        { value: 't', label_es: 't', label_en: 't' },
      ],
    })
    expect(validateField(unidad, 'kg')).toBeNull()
    expect(validateField(unidad, 'arrobas')).toEqual({ key: 'deca.validation.option' })
  })

  it('valida fechas', () => {
    expect(validateField(field({ type: 'date' }), '2026-10-05')).toBeNull()
    expect(validateField(field({ type: 'date' }), '32/13/2026')).toEqual({
      key: 'deca.validation.date',
    })
  })

  it('valida el formulario completo y devuelve un error por campo', () => {
    const fields = [
      field({ code: 'cargador_nif', type: 'nif', group: 'cargador', required: true }),
      field({ code: 'transportista_nif', type: 'nif', group: 'transportista', required: true }),
      field({ code: 'origen', group: 'envio', required: true }),
    ]
    const errors = validateAll(fields, {
      cargador_nif: '12345678Z',
      transportista_nif: 'malo',
      origen: '',
    })
    expect(Object.keys(errors)).toEqual(['transportista_nif', 'origen'])
    expect(errors.transportista_nif).toEqual({ key: 'deca.validation.nif' })
  })

  it('separa cargador contractual y transportista efectivo en bloques distintos', () => {
    const groups = groupFields([
      field({ code: 'transportista_nombre', group: 'transportista', order: 3 }),
      field({ code: 'cargador_nombre', group: 'cargador', order: 1 }),
      field({ code: 'cargador_nif', group: 'cargador', order: 2 }),
    ])
    expect(groups.map((entry) => entry.group)).toEqual(['cargador', 'transportista'])
    expect(groups[0].fields.map((entry) => entry.code)).toEqual([
      'cargador_nombre',
      'cargador_nif',
    ])
  })
})
