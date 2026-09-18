import { Toaster as Sonner, toast } from 'sonner'
import { useTheme } from '@/lib/theme'

/** MASTER §6: exito breve, error persistente con codigo. Nunca silencio. */
export function Toaster() {
  const { theme } = useTheme()
  return (
    <Sonner
      theme={theme === 'auto' ? 'system' : theme}
      position="bottom-right"
      closeButton
      duration={3000}
      toastOptions={{
        classNames: {
          toast: 'border border-border bg-card text-foreground rounded-md',
          description: 'text-muted-foreground',
          actionButton: 'bg-primary text-primary-foreground rounded-md cursor-pointer',
          cancelButton: 'bg-muted text-foreground rounded-md cursor-pointer',
        },
      }}
    />
  )
}

export { toast }
