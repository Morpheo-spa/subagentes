import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
} from '@tanstack/react-table'
import { CaretDown, CaretUp, DotsThree, Printer, Prohibit } from '@phosphor-icons/react'
import { useMemo } from 'react'
import { Guid } from '@/components/common/guid'
import { StatusBadge } from '@/components/common/status-badge'
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
import type { DocumentListParams, DocumentSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

export function DocumentsTable({
  documents,
  selection,
  onSelectionChange,
  onOpen,
  onPrint,
  onWithdraw,
  params,
  onSort,
}: {
  documents: DocumentSummary[]
  selection: RowSelectionState
  onSelectionChange: (selection: RowSelectionState) => void
  onOpen: (document: DocumentSummary) => void
  onPrint: (document: DocumentSummary) => void
  onWithdraw: (document: DocumentSummary) => void
  params: DocumentListParams
  onSort: (field: string) => void
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
            aria-label={t('documents.selectOne', { name: row.original.original_name })}
          />
        ),
      },
      {
        id: 'original_name',
        accessorKey: 'original_name',
        header: () => t('documents.columns.name'),
        cell: ({ row }) => (
          <button
            type="button"
            className="cursor-pointer text-left font-medium underline-offset-2 hover:underline"
            onClick={() => onOpen(row.original)}
          >
            {truncateMiddle(row.original.original_name, 48)}
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
          <StatusBadge status={row.original.status} expiresAt={row.original.expires_at} />
        ),
      },
      {
        id: 'uploaded_at',
        header: () => t('documents.columns.uploadedAt'),
        cell: ({ row }) => formatDate(row.original.uploaded_at, locale),
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
                aria-label={t('documents.rowActions', { name: row.original.original_name })}
              >
                <DotsThree size={20} aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onOpen(row.original)}>
                {t('documents.openDetail')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onPrint(row.original)}>
                <Printer size={16} aria-hidden="true" />
                {t('documents.addToQueue')}
              </DropdownMenuItem>
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

  const SORTABLE = new Set(['original_name', 'uploaded_at', 'expires_at', 'print_count'])

  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => {
              const sortable = SORTABLE.has(header.column.id)
              const active = params.sort === header.column.id
              return (
                <TableHead key={header.id} aria-sort={active ? (params.order === 'asc' ? 'ascending' : 'descending') : 'none'}>
                  {sortable ? (
                    <button
                      type="button"
                      className="flex cursor-pointer items-center gap-1 font-semibold"
                      onClick={() => onSort(header.column.id)}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {active ? (
                        params.order === 'asc' ? (
                          <CaretUp size={12} aria-hidden="true" />
                        ) : (
                          <CaretDown size={12} aria-hidden="true" />
                        )
                      ) : null}
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </TableHead>
              )
            })}
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
