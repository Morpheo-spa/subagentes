import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
} from '@tanstack/react-table'
import { DotsThree, Printer, Prohibit } from '@phosphor-icons/react'
import { useMemo } from 'react'
import { Guid } from '@/components/common/guid'
import { ComplianceBadge, StatusBadge } from '@/components/common/status-badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate, formatNumber, isExpiringSoon, truncateMiddle } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import type { DocumentSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Sin ordenacion por columna: `GET /documents/` no acepta `sort` ni `order`
 * (ver `_filters` en `app/routers/documents.py`). Antes que fingir un orden que
 * el servidor no aplica, no se ofrece.
 */
export function DocumentsTable({
  documents,
  selection,
  onSelectionChange,
  onOpen,
  onPrint,
  onWithdraw,
}: {
  documents: DocumentSummary[]
  selection: RowSelectionState
  onSelectionChange: (selection: RowSelectionState) => void
  onOpen: (document: DocumentSummary) => void
  onPrint: (document: DocumentSummary) => void
  onWithdraw: (document: DocumentSummary) => void
}) {
  const { t, locale } = useI18n()

  const columns = useMemo<ColumnDef<DocumentSummary>[]>(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllRowsSelected()
                ? true
                : table.getIsSomeRowsSelected()
                  ? 'indeterminate'
                  : false
            }
            onCheckedChange={(value) => table.toggleAllRowsSelected(Boolean(value))}
            aria-label={t('documents.selectAll')}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
            aria-label={t('documents.selectOne', { name: row.original.original_filename })}
          />
        ),
      },
      {
        id: 'original_filename',
        header: () => t('documents.columns.name'),
        cell: ({ row }) => (
          <button
            type="button"
            className="cursor-pointer text-left font-medium underline-offset-2 hover:underline"
            onClick={() => onOpen(row.original)}
          >
            {truncateMiddle(row.original.original_filename, 48)}
          </button>
        ),
      },
      {
        id: 'guid',
        header: () => t('documents.columns.guid'),
        cell: ({ row }) => <Guid value={row.original.id} short />,
      },
      {
        id: 'status',
        header: () => t('documents.columns.status'),
        cell: ({ row }) => (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge status={row.original.status} expiresAt={row.original.expires_at} />
            <ComplianceBadge status={row.original.compliance_status} />
          </div>
        ),
      },
      {
        id: 'created_at',
        header: () => t('documents.columns.uploadedAt'),
        cell: ({ row }) => formatDate(row.original.created_at, locale),
      },
      {
        id: 'expires_at',
        header: () => t('documents.columns.expiresAt'),
        cell: ({ row }) => formatDate(row.original.expires_at, locale),
      },
      {
        id: 'print_count',
        header: () => t('documents.columns.prints'),
        cell: ({ row }) => formatNumber(row.original.print_count, locale),
      },
      {
        id: 'actions',
        header: () => <span className="sr-only">{t('documents.columns.actions')}</span>,
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="iconSm"
                aria-label={t('documents.rowActions', { name: row.original.original_filename })}
              >
                <DotsThree size={16} aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onOpen(row.original)}>
                {t('documents.openDetail')}
              </DropdownMenuItem>
              {/* Solo se ofrece etiqueta para lo que es un DeCA valido. */}
              {row.original.is_valid_deca ? (
                <DropdownMenuItem onSelect={() => onPrint(row.original)}>
                  <Printer size={16} aria-hidden="true" />
                  {t('documents.addToQueue')}
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem variant="destructive" onSelect={() => onWithdraw(row.original)}>
                <Prohibit size={16} aria-hidden="true" />
                {t('documents.withdraw')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [t, locale, onOpen, onPrint, onWithdraw],
  )

  const table = useReactTable({
    data: documents,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    getRowId: (row) => row.id,
    state: { rowSelection: selection },
    onRowSelectionChange: (updater) => {
      onSelectionChange(typeof updater === 'function' ? updater(selection) : updater)
    },
  })

  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <TableHead key={header.id}>
                {flexRender(header.column.columnDef.header, header.getContext())}
              </TableHead>
            ))}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow
            key={row.id}
            data-state={row.getIsSelected() ? 'selected' : undefined}
            className={cn(
              // documents.md: caduca pronto -> borde izquierdo warning.
              isExpiringSoon(row.original.expires_at) && 'border-l-4 border-l-warning',
              row.original.withdrawn_at && 'text-muted-foreground',
            )}
          >
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
