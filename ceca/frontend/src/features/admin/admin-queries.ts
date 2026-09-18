import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AdminUser, Paginated, RetentionPolicy, Role, Site, StorageBackend } from '@/lib/types'

export function useSites() {
  return useQuery({ queryKey: ['admin', 'sites'], queryFn: () => api.get<Paginated<Site>>('/admin/sites') })
}

export function useAdminUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api.get<Paginated<AdminUser>>('/admin/users'),
  })
}

export function useRoles() {
  return useQuery({
    queryKey: ['admin', 'roles'],
    queryFn: () => api.get<{ items: Role[] }>('/admin/roles'),
    staleTime: 10 * 60_000,
  })
}

export function useStorageBackends() {
  return useQuery({
    queryKey: ['admin', 'storage'],
    queryFn: () => api.get<{ items: StorageBackend[] }>('/admin/storage-backends'),
  })
}

export function useRetentionPolicies() {
  return useQuery({
    queryKey: ['admin', 'retention'],
    queryFn: () => api.get<{ items: RetentionPolicy[] }>('/admin/retention-policies'),
  })
}

export function useUpdateRetention() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, days }: { id: string; days: number }) =>
      api.patch<RetentionPolicy>(`/admin/retention-policies/${id}`, { retention_days: days }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'retention'] })
    },
  })
}
