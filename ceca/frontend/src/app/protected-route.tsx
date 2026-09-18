import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Prohibit } from '@phosphor-icons/react'
import { EmptyState } from '@/components/common/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth, useSessionPermissions } from '@/lib/auth'
import { useI18n } from '@/lib/i18n'
import { hasPermission, type Permission } from '@/lib/permissions'

/**
 * Oculta lo que el usuario no puede usar. No es seguridad: el backend
 * revalida siempre con `require_permission` (CLAUDE.md §3).
 */
export function ProtectedRoute({ permission }: { permission?: Permission }) {
  const { user, status } = useAuth()
  const session = useSessionPermissions()
  const { t } = useI18n()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex flex-col gap-4 p-6" aria-busy="true">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (status === 'anonymous' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  if (permission && !hasPermission(session, permission)) {
    return (
      <EmptyState
        icon={Prohibit}
        title={t('errors.forbiddenTitle')}
        description={t('errors.forbiddenBody')}
      />
    )
  }

  return <Outlet />
}
