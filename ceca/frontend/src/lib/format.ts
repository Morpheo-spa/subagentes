/** Formateo con `Intl`. Sin moment, sin date-fns. */
import type { Locale } from './types'

const LOCALE_TAG: Record<Locale, string> = { es: 'es-ES', en: 'en-GB' }

export function localeTag(locale: Locale): string {
  return LOCALE_TAG[locale] ?? LOCALE_TAG.es
}

const dateTimeCache = new Map<string, Intl.DateTimeFormat>()

function dtf(locale: Locale, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}:${JSON.stringify(options)}`
  let formatter = dateTimeCache.get(key)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(localeTag(locale), options)
    dateTimeCache.set(key, formatter)
  }
  return formatter
}

function parse(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Fecha corta: 18/09/2026. */
export function formatDate(value: string | Date | null | undefined, locale: Locale): string {
  const date = parse(value)
  if (!date) return '—'
  return dtf(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date)
}

/** Fecha y hora: 18/09/2026, 14:32. */
export function formatDateTime(value: string | Date | null | undefined, locale: Locale): string {
  const date = parse(value)
  if (!date) return '—'
  return dtf(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** Valor para `<input type="date">` (siempre ISO, nunca localizado). */
export function toDateInputValue(value: string | Date | null | undefined): string {
  const date = parse(value)
  if (!date) return ''
  return date.toISOString().slice(0, 10)
}

export function formatNumber(
  value: number,
  locale: Locale,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(localeTag(locale), options).format(value)
}

/** Importe en centimos -> "12,00 €". */
export function formatMoney(cents: number, currency: string, locale: Locale): string {
  return new Intl.NumberFormat(localeTag(locale), {
    style: 'currency',
    currency: currency || 'EUR',
  }).format(cents / 100)
}

const SIZE_UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const

/** Tamano de fichero con `Intl.NumberFormat` (unidades base 1000). */
export function formatBytes(bytes: number, locale: Locale): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  let value = bytes
  let unitIndex = 0
  while (value >= 1000 && unitIndex < SIZE_UNITS.length - 1) {
    value /= 1000
    unitIndex += 1
  }
  return new Intl.NumberFormat(localeTag(locale), {
    style: 'unit',
    unit: SIZE_UNITS[unitIndex],
    unitDisplay: 'short',
    maximumFractionDigits: unitIndex === 0 ? 0 : 1,
  }).format(value)
}

const DIVISIONS: { amount: number; unit: Intl.RelativeTimeFormatUnit }[] = [
  { amount: 60, unit: 'second' },
  { amount: 60, unit: 'minute' },
  { amount: 24, unit: 'hour' },
  { amount: 7, unit: 'day' },
  { amount: 4.34524, unit: 'week' },
  { amount: 12, unit: 'month' },
  { amount: Number.POSITIVE_INFINITY, unit: 'year' },
]

export function formatRelative(
  value: string | Date | null | undefined,
  locale: Locale,
  now: Date = new Date(),
): string {
  const date = parse(value)
  if (!date) return '—'
  const rtf = new Intl.RelativeTimeFormat(localeTag(locale), { numeric: 'auto' })
  let duration = (date.getTime() - now.getTime()) / 1000
  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return rtf.format(Math.round(duration), division.unit)
    }
    duration /= division.amount
  }
  return formatDate(date, locale)
}

/** Dias que faltan (negativo = ya vencido). */
export function daysUntil(value: string | Date | null | undefined, now: Date = new Date()): number | null {
  const date = parse(value)
  if (!date) return null
  return Math.ceil((date.getTime() - now.getTime()) / 86_400_000)
}

export const EXPIRY_WARNING_DAYS = 30

/** documents.md: "Caduca < 30 d" -> badge warning. */
export function isExpiringSoon(value: string | Date | null | undefined, now: Date = new Date()): boolean {
  const days = daysUntil(value, now)
  return days !== null && days >= 0 && days < EXPIRY_WARNING_DAYS
}

/** GUID corto para etiqueta y visor publico (label-template.md §3). */
export function shortId(guid: string): string {
  return guid.replace(/-/g, '').slice(0, 8).toUpperCase()
}

export function truncateMiddle(value: string, max = 42): string {
  if (value.length <= max) return value
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`
}

/** Lista legible ("a, b y c" / "a, b, and c"). Con `Intl`, sin concatenar comas. */
export function formatList(items: string[], locale: Locale): string {
  return new Intl.ListFormat(localeTag(locale), { style: 'long', type: 'conjunction' }).format(items)
}
