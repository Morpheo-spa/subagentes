/**
 * Permisos `<recurso>:<accion>`. El backend vuelve a comprobarlos siempre
 * (`require_permission`): esto es solo para no ensenar lo que no se puede usar.
 */
import type { CurrentUser } from './types'

export const PERMISSIONS = {
  documentsRead: 'documents:read',
  documentsCreate: 'documents:create',
  documentsUpdate: 'documents:update',
  documentsWithdraw: 'documents:withdraw',
  documentsExport: 'documents:export',
  decaRead: 'deca:read',
  decaWrite: 'deca:write',
  printingRead: 'printing:read',
  printingCreate: 'printing:create',
  billingRead: 'billing:read',
  billingManage: 'billing:manage',
  adminSites: 'admin:sites',
  adminUsers: 'admin:users',
  adminStorage: 'admin:storage',
  adminRetention: 'admin:retention',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]

export function hasPermission(user: CurrentUser | null, permission: Permission): boolean {
  if (!user) return false
  if (user.is_superuser) return true
  return user.permissions.includes(permission)
}

export function hasAnyPermission(user: CurrentUser | null, permissions: Permission[]): boolean {
  return permissions.some((permission) => hasPermission(user, permission))
}
