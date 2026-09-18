import { CaretLeft, CaretRight } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useI18n } from '@/lib/i18n'
import { formatNumber } from '@/lib/format'

const PAGE_SIZES = [10, 25, 50, 100]

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}) {
  const { t, locale } = useI18n()
  const pages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <nav
      aria-label={t('pagination.label')}
      className="flex flex-col items-center justify-between gap-3 border-t border-border pt-4 sm:flex-row"
    >
      <p className="text-sm text-muted-foreground">
        {t('pagination.summary', {
          page: formatNumber(page, locale),
          pages: formatNumber(pages, locale),
          total: formatNumber(total, locale),
        })}
      </p>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          {t('pagination.perPage')}
          <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
            <SelectTrigger className="h-9 w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {formatNumber(size, locale)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <Button
          variant="outline"
          size="iconSm"
          aria-label={t('pagination.previous')}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <CaretLeft size={16} aria-hidden="true" />
        </Button>
        <Button
          variant="outline"
          size="iconSm"
          aria-label={t('pagination.next')}
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
        >
          <CaretRight size={16} aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}
