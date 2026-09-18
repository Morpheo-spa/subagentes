import { describe, expect, it } from 'vitest'
import en from './en.json'
import es from './es.json'

type Dict = Record<string, unknown>

function flatten(dict: Dict, prefix = ''): string[] {
  return Object.entries(dict).flatMap(([key, value]) =>
    value && typeof value === 'object'
      ? flatten(value as Dict, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )
}

function params(value: string): string[] {
  return [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort()
}

function get(dict: Dict, key: string): string {
  return key.split('.').reduce<unknown>((acc, part) => (acc as Dict)?.[part], dict) as string
}

describe('catalogo i18n', () => {
  it('es.json y en.json tienen exactamente las mismas claves', () => {
    expect(flatten(en as Dict).sort()).toEqual(flatten(es as Dict).sort())
  })

  it('cada cadena usa los mismos parametros en los dos idiomas', () => {
    for (const key of flatten(es as Dict)) {
      expect({ key, params: params(get(en as Dict, key)) }).toEqual({
        key,
        params: params(get(es as Dict, key)),
      })
    }
  })
})
