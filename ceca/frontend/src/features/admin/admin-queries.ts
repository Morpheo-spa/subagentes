import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from '@/lib/api'
import * as routes from '@/lib/routes'
import type {
  PageResponse,
  RetentionPolicyRead,
  RoleCatalogResponse,
  SiteRead,
  StorageBackendRead,
  UserRead,
} from '@/lib/types'

/** Cada area cuelga de su propio router: `/sites/`, `/users/`, `/storage/`, `/retention/`. */
export function useSites() {
  return useQuery({
    queryKey: ['admin', 'sites'],
    queryFn: () => request<PageResponse<SiteRead>>(routes.sitesList()),
  })
}

export function useAdminUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => request<PageResponse<UserRead>>(routes.usersList()),
  })
}

/** Roles y vocabulario de permisos: la UI no los hardcodea. */
export function useRoles() {
  return useQuery({
    queryKey: ['admin', 'roles'],
    queryFn: () => request<RoleCatalogResponse>(routes.usersRoles()),
    staleTime: 10 * 60_000,
  })
}

export function useStorageBackends() {
  return useQuery({
    queryKey: ['admin', 'storage'],
    queryFn: () => request<PageResponse<StorageBackendRead>>(routes.storageList()),
  })
}

export function useRetentionPolicies() {
  return useQuery({
    queryKey: ['admin', 'retention'],
    queryFn: () => request<PageResponse<RetentionPolicyRead>>(routes.retentionList()),
  })
}

/** `version` va en el cuerpo: bloqueo optimista del backend. */
export function useUpdateRetention() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, days, version }: { id: string; days: number; version: number }) =>
      request<RetentionPolicyRead>(routes.retentionUpdate({ policyId: id }), {
        body: { retention_days: days, version },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'retention'] })
    },
  })
}
