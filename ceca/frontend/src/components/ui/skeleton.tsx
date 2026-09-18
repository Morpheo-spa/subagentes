import type * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * MASTER §6: reserva espacio (CLS < 0.1). Sin parpadeo: opacidad fija,
 * `prefers-reduced-motion` ya desactiva la animacion global.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded-md bg-muted', className)}
      {...props}
    />
  )
}
