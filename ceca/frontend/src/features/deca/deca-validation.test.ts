import { describe, expect, it } from 'vitest'
import type { DecaFieldRead } from '@/lib/types'
import { blockOf, groupFields, missingRequired } from './deca-catalog'
import { isValidTaxId, partiesAreDistinct, validateAll, validateField } from './deca-validation'

function field(overrides: Partial<DecaFieldRead>): DecaFieldRead {
  return {
    code: 'campo',
    label_es: 'Campo',
    label_en: 'Field',
    help_es: null,
    help_en: null,
    data_type: 'string',
    is_required: false,
    max_length: null,
    pattern: null,
    choices: [],
    legal_reference: null,
    sort_order: 1,
    ...overrides,
  }
}

describe('validador DeCA', () => {
  it('exige los campos marcados como is_required en el catalogo', () => {
    expect(validateField(field({ is_required: true }), '')).toEqual({
      key: 'deca.validation.required',
    })
    expect(validateField(field({ is_required: true }), '   ')).toEqual({
      key: 'deca.validation.required',
    })
    expect(validateField(field({ is_required: false }), '')).toBeNull()
  })

  it('valida NIF, NIE y CIF por digito de control, como el backend', () => {
    expect(isValidTaxId('12345678Z')).toBe(true)
    expect(isValidTaxId('12345678A')).toBe(false)
    expect(isValidTaxId('X1234567L')).toBe(true)
    expect(isValidTaxId('B12345674')).toBe(true)
    expect(isValidTaxId('B12345673')).toBe(false)
    expect(isValidTaxId('no-es-un-nif')).toBe(false)
  })

  it('aplica el digito de control a cualquier campo que acabe en _nif', () => {
    // El backend usa el sufijo del code (TAX_ID_SUFFIX), no una lista de campos.
    const nif = field({ code: 'cargador_nif', max_length: 16, pattern: '^[A-Za-z0-9]{8,16}$' })
    expect(validateField(nif, '12345678Z')).toBeNull()
    expect(validateField(nif, '12345678A')).toEqual({ key: 'deca.validation.nif' })
    // Mismo valor en un campo que no es un NIF: no se le aplica.
    expect(validateField(field({ code: 'origen' }), '12345678A')).toBeNull()
  })

  it('exige numero positivo en decimal, como `_is_positive_number`', () => {
    const peso = field({ code: 'mercancia_peso', data_type: 'decimal', is_required: true })
    expect(validateField(peso, '1200')).toBeNull()
    expect(validateField(peso, '1200,5')).toBeNull()
    expect(validateField(peso, '0')).toEqual({ key: 'deca.validation.type.decimal' })
    expect(validateField(peso, 'mucho')).toEqual({ key: 'deca.validation.type.decimal' })
  })

  it('respeta max_length, pattern y choices del catalogo', () => {
    expect(validateField(field({ max_length: 3 }), 'abcd')).toEqual({
      key: 'deca.validation.maxLength',
      params: { max: 3 },
    })
    expect(validateField(field({ pattern: '^[A-Z]+$' }), 'abc')).toEqual({
      key: 'deca.validation.pattern',
    })
    const unidad = field({ data_type: 'enum', choices: ['kg', 't'] })
    expect(validateField(unidad, 'kg')).toBeNull()
    expect(validateField(unidad, 'arrobas')).toEqual({ key: 'deca.validation.type.enum' })
  })

  it('valida fechas', () => {
    expect(validateField(field({ data_type: 'date' }), '2026-10-05')).toBeNull()
    expect(validateField(field({ data_type: 'date' }), '32/13/2026')).toEqual({
      key: 'deca.validation.type.date',
    })
  })

  it('valida el formulario completo y devuelve un error por campo', () => {
    const fields = [
      field({ code: 'cargador_nif', is_required: true }),
      field({ code: 'transportista_nif', is_required: true }),
      field({ code: 'origen', is_required: true }),
    ]
    const errors = validateAll(fields, {
      cargador_nif: '12345678Z',
      transportista_nif: 'malo',
      origen: '',
    })
    expect(Object.keys(errors)).toEqual(['transportista_nif', 'origen'])
    expect(errors.transportista_nif).toEqual({ key: 'deca.validation.nif' })
  })

  it('exige que las dos partes se distingan (art. 6)', () => {
    const fields = [field({ code: 'cargador_nif' }), field({ code: 'transportista_nif' })]
    expect(
      partiesAreDistinct(fields, { cargador_nif: '12345678Z', transportista_nif: 'B12345674' }),
    ).toBe(true)
    expect(
      partiesAreDistinct(fields, { cargador_nif: '12345678Z', transportista_nif: '12345678-Z' }),
    ).toBe(false)
  })
})

describe('bloques del formulario', () => {
  it('separa cargador contractual y transportista efectivo en bloques distintos', () => {
    const groups = groupFields([
      field({ code: 'transportista_nombre', sort_order: 30 }),
      field({ code: 'cargador_nombre', sort_order: 10 }),
      field({ code: 'cargador_nif', sort_order: 20 }),
    ])
    expect(groups.map((entry) => entry.block)).toEqual(['cargador', 'transportista'])
    expect(groups[0].fields.map((entry) => entry.code)).toEqual([
      'cargador_nombre',
      'cargador_nif',
    ])
  })

  it('un campo que el catalogo estrene no desaparece: cae en el bloque de envio', () => {
    // El catalogo no manda grupo, asi que lo que no es de una parte va a envio.
    expect(blockOf(field({ code: 'numero_bultos' }))).toBe('envio')
    const groups = groupFields([field({ code: 'numero_bultos' })])
    expect(groups).toHaveLength(1)
    expect(groups[0].fields[0].code).toBe('numero_bultos')
  })

  it('lista los obligatorios que siguen vacios', () => {
    const fields = [
      field({ code: 'origen', is_required: true }),
      field({ code: 'destino', is_required: true }),
      field({ code: 'observaciones', is_required: false }),
    ]
    expect(missingRequired(fields, { origen: 'Madrid' }).map((entry) => entry.code)).toEqual([
      'destino',
    ])
  })
})
