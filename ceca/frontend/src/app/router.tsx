import { lazy, Suspense } from 'react'
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Outlet,
  Route,
  RouterProvider,
} from 'react-router-dom'
import { FileMagnifyingGlass } from '@phosphor-icons/react'
import { EmptyState } from '@/components/common/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/lib/i18n'
import { PERMISSIONS } from '@/lib/permissions'
import { AppShell } from './app-shell'
import { ProtectedRoute } from './protected-route'

const LoginPage = lazy(() => import('@/features/auth/login-page'))
const UploadPage = lazy(() => import('@/features/upload/upload-page'))
const DecaGeneratePage = lazy(() => import('@/features/deca/deca-generate-page'))
const DecaEditPage = lazy(() => import('@/features/deca/deca-edit-page'))
const DocumentsPage = lazy(() => import('@/features/documents/documents-page'))
const PrintingPage = lazy(() => import('@/features/printing/printing-page'))
const BillingPage = lazy(() => import('@/features/billing/billing-page'))
const AdminPage = lazy(() => import('@/features/admin/admin-page'))
const PublicViewerPage = lazy(() => import('@/features/public/public-viewer-page'))

/** Skeleton de ruta: reserva espacio, no parpadea (MASTER §6). */
function RouteFallback() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-5 w-96 max-w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}

function SuspenseLayout() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Outlet />
    </Suspense>
  )
}

function NotFoundPage() {
  const { t } = useI18n()
  return (
    <EmptyState
      icon={FileMagnifyingGlass}
      title={t('errors.notFoundTitle')}
      description={t('errors.notFoundBody')}
    />
  )
}

/**
 * Router de datos (no `<BrowserRouter>`): hace falta para `useBlocker`, que es
 * lo que confirma la salida con subidas en curso (upload.md).
 */
const routes = createRoutesFromElements(
  <Route element={<SuspenseLayout />}>
    {/* Visor publico por QR: sin app shell (public-viewer.md). */}
    <Route path="/v/:token" element={<PublicViewerPage />} />
    <Route path="/login" element={<LoginPage />} />

    <Route element={<ProtectedRoute />}>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/upload" replace />} />

        <Route element={<ProtectedRoute permission={PERMISSIONS.documentsCreate} />}>
          <Route path="/upload" element={<UploadPage />} />
        </Route>

        <Route element={<ProtectedRoute permission={PERMISSIONS.decaWrite} />}>
          <Route path="/deca/new" element={<DecaGeneratePage />} />
          <Route path="/deca/:documentId" element={<DecaEditPage />} />
        </Route>

        <Route element={<ProtectedRoute permission={PERMISSIONS.documentsRead} />}>
          <Route path="/documents" element={<DocumentsPage />} />
        </Route>

        <Route element={<ProtectedRoute permission={PERMISSIONS.printingRead} />}>
          <Route path="/printing" element={<PrintingPage />} />
        </Route>

        <Route element={<ProtectedRoute permission={PERMISSIONS.billingRead} />}>
          <Route path="/billing" element={<BillingPage />} />
        </Route>

        <Route element={<ProtectedRoute permission={PERMISSIONS.adminUsers} />}>
          <Route path="/admin" element={<AdminPage />} />
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Route>
  </Route>,
)

export const router = createBrowserRouter(routes)

export function AppRouter() {
  return <RouterProvider router={router} />
}
