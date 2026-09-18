/**
 * i18n ES/EN. ES es el idioma por defecto y el fallback (`.claude/rules/i18n.md`).
 * Ningun literal en JSX: todo pasa por `t()`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import en from '@/locales/en.json'
import es from '@/locales/es.json'
import { setApiLocale } from './api'
import type { Locale } from './types'

export const LOCALES: Locale[] = ['es', 'en']
export const DEFAULT_LOCALE: Locale = 'es'
const STORAGE_KEY = 'estampa.locale'

type Dict = Record<string, unknown>
const DICTS: Record<Locale, Dict> = { es: es as Dict, en: en as Dict }

export type TParams = Record<string, string | number>

function lookup(dict: Dict, key: string): string | undefined {
  const value = key.split('.').reduce<unknown>((acc, part) => {
    if (acc && typeof acc === 'object') return (acc as Dict)[part]
    return undefined
  }, dict)
  return typeof value === 'string' ? value : undefined
}

function interpolate(template: string, params?: TParams): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  )
}

export function translate(locale: Locale, key: string, params?: TParams): string {
  const raw = lookup(DICTS[locale], key) ?? lookup(DICTS[DEFAULT_LOCALE], key)
  if (raw === undefined) {
    if (import.meta.env.DEV) console.warn(`[i18n] falta la clave "${key}"`)
    return key
  }
  return interpolate(raw, params)
}

export function isLocale(value: unknown): value is Locale {
  return value === 'es' || value === 'en'
}

/** Idioma del navegador la primera vez; despues, la preferencia guardada. */
export function detectLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (isLocale(stored)) return stored
  } catch {
    /* almacenamiento bloqueado: seguimos con la deteccion */
  }
  const candidates = typeof navigator !== 'undefined' ? (navigator.languages ?? [navigator.language]) : []
  for (const candidate of candidates) {
    const base = candidate?.slice(0, 2).toLowerCase()
    if (isLocale(base)) return base
  }
  return DEFAULT_LOCALE
}

export interface I18nValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: TParams) => string
  /** Elige `label_es` / `label_en` de un catalogo de la API. */
  pick: (source: object, base: string) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => detectLocale())

  useEffect(() => {
    document.documentElement.lang = locale
    setApiLocale(locale)
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    setApiLocale(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* preferencia no persistible: no es critico */
    }
  }, [])

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale,
      t: (key, params) => translate(locale, key, params),
      pick: (source, base) => {
        const record = source as Record<string, unknown>
        const localized = record[`${base}_${locale}`]
        if (typeof localized === 'string') return localized
        const fallback = record[`${base}_${DEFAULT_LOCALE}`]
        return typeof fallback === 'string' ? fallback : ''
      },
    }),
    [locale, setLocale],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n fuera de I18nProvider')
  return ctx
}

export function useT(): I18nValue['t'] {
  return useI18n().t
}
