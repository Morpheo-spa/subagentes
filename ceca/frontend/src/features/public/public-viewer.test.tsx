import { screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/render'
import PublicViewerPage from './public-viewer-page'

function renderViewer(token: string) {
  return renderWithProviders(
    <MemoryRouter initialEntries={[`/v/${token}`]}>
      <Routes>
        <Route path="/v/:token" element={<PublicViewerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function errorResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('visor publico', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('no revela si el documento existio: retirado y no encontrado se ven igual', async () => {
    // Token revocado / documento retirado.
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          errorResponse(410, { detail: { code: 'DOCUMENT_WITHDRAWN', message: 'Retirado' } }),
        ),
    )
    const withdrawn = renderViewer('token-de-documento-retirado')
    await waitFor(() => expect(screen.getByRole('heading')).toBeInTheDocument())
    const withdrawnHtml = withdrawn.container.innerHTML
    withdrawn.unmount()

    vi.unstubAllGlobals()

    // Token que nunca existio.
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          errorResponse(404, { detail: { code: 'NOT_FOUND', message: 'No encontrado' } }),
        ),
    )
    const missing = renderViewer('token-inventado')
    await waitFor(() => expect(screen.getByRole('heading')).toBeInTheDocument())
    const missingHtml = missing.container.innerHTML

    expect(missingHtml).toBe(withdrawnHtml)
  })

  it('no filtra el codigo ni el mensaje de error de la API', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          errorResponse(410, {
            detail: { code: 'DOCUMENT_WITHDRAWN', message: 'Retirado el 2026-01-02 por auditoría' },
          }),
        ),
    )

    const { container } = renderViewer('token-de-documento-retirado')
    await waitFor(() => expect(screen.getByRole('heading')).toBeInTheDocument())

    expect(container.textContent).not.toContain('DOCUMENT_WITHDRAWN')
    expect(container.textContent).not.toContain('auditoría')
    expect(container.textContent).not.toContain('2026-01-02')
  })

  it('muestra el documento cuando el token es valido', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            original_name: 'albaran-2026-0001.pdf',
            short_id: 'A1B2C3D4',
            uploaded_at: '2026-09-01T10:00:00Z',
            tenant_name: 'Planta Norte',
            file_url: '/api/v1/public/tok/file',
            size_bytes: 12345,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    renderViewer('token-valido')

    await waitFor(() => expect(screen.getByText('albaran-2026-0001.pdf')).toBeInTheDocument())
    expect(screen.getByText('Planta Norte')).toBeInTheDocument()
  })
})
