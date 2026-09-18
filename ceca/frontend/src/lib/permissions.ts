/**
 * Permisos `<recurso>:<accion>`, copiados de `app/models/tenancy.py:PERMISSIONS`.
 * El backend vuelve a comprobarlos siempre (`require_permission`): esto es solo
 * para no ensenar lo que no se puede usar.
 *
 * Los nombres son identificadores y no se traducen (`.claude/rules/i18n.md`).
 */

export const PERMISSIONS = {
  documentsRead: 'documents:read',
  documentsCreate: 'documents:create',
  documentsUpdate: 'documents:update',
  documentsWithdraw: 'documents:withdraw',
  documentsExport: 'documents:export',
  shareRevoke: 'share:revoke',
  printingRead: 'printing:read',
  printingQueue: 'printing:queue',
  printingPrint: 'printing:print',
  storageRead: 'storage:read',
  storageManage: 'storage:manage',
  retentionRead: 'retention:read',
  retentionManage: 'retention:manage',
  billingRead: 'billing:read',
  billingManage: 'billing:manage',
  usersRead: 'users:read',
  usersManage: 'users:manage',
  sitesRead: 'sites:read',
  sitesManage: 'sites:manage',
  auditRead: 'audit:read',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]

/** Lo que el backend concede en la sesion: usuario + permisos del site activo. */
export interface PermissionHolder {
  is_superuser: boolean
  permissions: string[]
}

export function hasPermission(holder: PermissionHolder | null, permission: Permission): boolean {
  if (!holder) return false
  if (holder.is_superuser) return true
  return holder.permissions.includes(permission)
}

export function hasAnyPermission(
  holder: PermissionHolder | null,
  permissions: Permission[],
): boolean {
  return permissions.some((permission) => hasPermission(holder, permission))
}
