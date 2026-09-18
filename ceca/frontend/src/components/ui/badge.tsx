import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'
import { cn } from '@/lib/utils'

/** MASTER §6: el Badge lleva SIEMPRE icono + texto, nunca solo color. */
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-muted text-muted-foreground',
        primary: 'border-transparent bg-primary-surface text-primary',
        secondary: 'border-transparent bg-secondary-surface text-secondary',
        success: 'border-transparent bg-accent-surface text-accent-text',
        warning: 'border-transparent bg-warning-surface text-warning-text',
        destructive: 'border-transparent bg-destructive-surface text-destructive-text',
        outline: 'border-border bg-transparent text-foreground',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { badgeVariants }
