import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { I18nProvider } from '@/lib/i18n'
import { ThemeProvider } from '@/lib/theme'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
}

export function renderWithProviders(ui: ReactElement, options?: RenderOptions) {
  const queryClient = createTestQueryClient()
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <ThemeProvider>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </I18nProvider>
    </ThemeProvider>
  )
  return render(ui, { wrapper: Wrapper, ...options })
}
