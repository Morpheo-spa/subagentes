import type { ReactNode } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useI18n } from '@/lib/i18n'

/**
 * MASTER §6: toda accion destructiva pasa por AlertDialog y el texto
 * nombra el objeto. `objectName` es obligatorio a proposito.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  objectName,
  confirmLabel,
  onConfirm,
  destructive = true,
  extra,
  disabled,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  objectName: string
  confirmLabel: string
  onConfirm: () => void
  destructive?: boolean
  extra?: ReactNode
  disabled?: boolean
}) {
  const { t } = useI18n()
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>
            {description}{' '}
            <strong className="font-semibold text-foreground">{objectName}</strong>
          </AlertDialogDescription>
        </AlertDialogHeader>
        {extra}
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? 'destructive' : 'default'}
            disabled={disabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
