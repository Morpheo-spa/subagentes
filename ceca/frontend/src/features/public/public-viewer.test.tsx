import { screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectLocale, translate } from '@/lib/i18n'
import { renderWithProviders } from '@/test/render'

/** El idioma lo decide el navegador del test: se compara por clave, no por texto. */
const text = (key: string) => translate(detectLocale(), key)
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

/** `PublicDocumentView` tal y como lo devuelve `GET /v/{token}`. */
function publicView(overrides: Record<string, unknown> = {}) {
  return new Response(
    JSON.stringify({
      original_filename: 'albaran-2026-0001.pdf',
      issued_at: '2026-09-01T10:00:00Z',
      revision: 0,
      is_valid_deca: true,
      compliance_status: 'compliant',
      deca: {},
      file_url: '/v/token-valido/file',
      site_name: 'Planta Norte',
      ...overrides,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
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
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(publicView())))

    renderViewer('token-valido')

    await waitFor(() => expect(screen.getByText('albaran-2026-0001.pdf')).toBeInTheDocument())
    expect(screen.getByText('Planta Norte')).toBeInTheDocument()
  })

  it('un escaneo no se presenta como DeCA valido, tampoco en carretera', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(publicView({ is_valid_deca: false, compliance_status: 'not_a_deca' })),
      ),
    )

    renderViewer('token-de-un-escaneo')

    await waitFor(() =>
      expect(screen.getByText(text('compliance.not_a_deca'))).toBeInTheDocument(),
    )
    expect(screen.queryByText(text('compliance.compliant'))).not.toBeInTheDocument()
  })
})
