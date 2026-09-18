import { Buildings, HardDrives, ShieldWarning, Users, WarningCircle } from '@phosphor-icons/react'
import { useState } from 'react'
import { ErrorState } from '@/components/common/error-state'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import { useI18n } from '@/lib/i18n'
import {
  useAdminUsers,
  useRetentionPolicies,
  useRoles,
  useSites,
  useStorageBackends,
  useUpdateRetention,
} from './admin-queries'

function SitesTab() {
  const { t, locale } = useI18n()
  const sites = useSites()
  if (sites.isPending) return <Skeleton className="h-64 w-full" />
  if (sites.isError) return <ErrorState error={sites.error} onRetry={() => void sites.refetch()} />

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('admin.sites.name')}</TableHead>
          <TableHead>{t('admin.sites.prefix')}</TableHead>
          <TableHead>{t('admin.sites.users')}</TableHead>
          <TableHead>{t('admin.sites.createdAt')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sites.data.items.map((site) => (
          <TableRow key={site.id}>
            <TableCell className="font-medium">{site.name}</TableCell>
            <TableCell>
              <code className="estampa-mono text-meta">{site.site_prefix}</code>
            </TableCell>
            <TableCell>{formatNumber(site.users_count, locale)}</TableCell>
            <TableCell>{formatDate(site.created_at, locale)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function UsersTab() {
  const { t, locale, pick } = useI18n()
  const users = useAdminUsers()
  const roles = useRoles()
  if (users.isPending) return <Skeleton className="h-64 w-full" />
  if (users.isError) return <ErrorState error={users.error} onRetry={() => void users.refetch()} />

  const roleLabel = (code: string) => {
    const role = roles.data?.items.find((entry) => entry.code === code)
    return role ? pick(role, 'name') : code
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('admin.users.name')}</TableHead>
          <TableHead>{t('admin.users.email')}</TableHead>
          <TableHead>{t('admin.users.roles')}</TableHead>
          <TableHead>{t('admin.users.sites')}</TableHead>
          <TableHead>{t('admin.users.lastLogin')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.data.items.map((user) => (
          <TableRow key={user.id}>
            <TableCell className="font-medium">{user.full_name}</TableCell>
            <TableCell>{user.email}</TableCell>
            <TableCell>
              <span className="flex flex-wrap gap-1">
                {user.roles.map((role) => (
                  <Badge key={role} variant="outline">
                    {roleLabel(role)}
                  </Badge>
                ))}
              </span>
            </TableCell>
            <TableCell>{user.sites.map((site) => site.name).join(', ')}</TableCell>
            <TableCell>
              {user.last_login_at ? formatDateTime(user.last_login_at, locale) : t('common.never')}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function StorageTab() {
  const { t, locale } = useI18n()
  const backends = useStorageBackends()
  if (backends.isPending) return <Skeleton className="h-64 w-full" />
  if (backends.isError)
    return <ErrorState error={backends.error} onRetry={() => void backends.refetch()} />

  return (
    <div className="flex flex-col gap-4">
      {/* rules/backend.md: las credenciales NO se devuelven por la API, ni enmascaradas. */}
      <p className="flex items-start gap-2 rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">
        <ShieldWarning size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
        {t('admin.storage.secretsNotice')}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('admin.storage.name')}</TableHead>
            <TableHead>{t('admin.storage.kind')}</TableHead>
            <TableHead>{t('admin.storage.health')}</TableHead>
            <TableHead>{t('admin.storage.config')}</TableHead>
            <TableHead>{t('admin.storage.lastChecked')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {backends.data.items.map((backend) => (
            <TableRow key={backend.id}>
              <TableCell className="font-medium">
                {backend.name}
                {backend.is_default ? (
                  <Badge variant="primary" className="ml-2">
                    {t('admin.storage.default')}
                  </Badge>
                ) : null}
              </TableCell>
              <TableCell>{t(`admin.storage.kinds.${backend.kind}`)}</TableCell>
              <TableCell>
                <Badge
                  variant={
                    backend.health === 'ok'
                      ? 'success'
                      : backend.health === 'down'
                        ? 'destructive'
                        : 'warning'
                  }
                >
                  <HardDrives size={14} aria-hidden="true" />
                  {t(`admin.storage.healths.${backend.health}`)}
                </Badge>
              </TableCell>
              <TableCell>
                <dl className="flex flex-col gap-0.5 text-meta text-muted-foreground">
                  {Object.entries(backend.public_config).map(([key, value]) => (
                    <div key={key} className="flex gap-1">
                      <dt>{key}:</dt>
                      <dd className="estampa-mono">{value}</dd>
                    </div>
                  ))}
                </dl>
              </TableCell>
              <TableCell>
                {backend.last_checked_at
                  ? formatDateTime(backend.last_checked_at, locale)
                  : t('common.never')}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function RetentionTab() {
  const { t, locale } = useI18n()
  const policies = useRetentionPolicies()
  const update = useUpdateRetention()
  const [drafts, setDrafts] = useState<Record<string, number>>({})

  if (policies.isPending) return <Skeleton className="h-64 w-full" />
  if (policies.isError)
    return <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />

  return (
    <div className="flex flex-col gap-4">
      {policies.data.items.map((policy) => {
        const value = drafts[policy.id] ?? policy.retention_days
        // docs/DECA.md §6: 365 dias es el minimo legal; la UI avisa al dejarlo ahi.
        const atMinimum = value <= policy.legal_minimum_days
        return (
          <div key={policy.id} className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
            <p className="font-medium">{policy.site_name}</p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-2">
                <Label htmlFor={`retention-${policy.id}`}>{t('admin.retention.days')}</Label>
                <Input
                  id={`retention-${policy.id}`}
                  type="number"
                  min={policy.legal_minimum_days}
                  className="w-32"
                  value={value}
                  onChange={(event) =>
                    setDrafts((current) => ({
                      ...current,
                      [policy.id]: Math.max(0, Number(event.target.value) || 0),
                    }))
                  }
                />
              </div>
              <Button
                disabled={update.isPending || value === policy.retention_days}
                onClick={() =>
                  update.mutate(
                    { id: policy.id, days: value },
                    {
                      onSuccess: () => toast.success(t('admin.retention.saved')),
                      onError: (error) =>
                        toast.error(
                          error instanceof ApiError ? error.message : t('errors.unexpected'),
                        ),
                    },
                  )
                }
              >
                {t('common.save')}
              </Button>
            </div>
            {atMinimum ? (
              <p className="flex items-start gap-2 rounded-md border border-warning bg-warning-surface p-3 text-sm text-warning-text">
                <WarningCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                {t('admin.retention.minimumWarning', {
                  days: formatNumber(policy.legal_minimum_days, locale),
                })}
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export default function AdminPage() {
  const { t } = useI18n()
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('admin.title')} description={t('admin.subtitle')} />
      <Tabs defaultValue="sites">
        <TabsList>
          <TabsTrigger value="sites">
            <Buildings size={16} aria-hidden="true" />
            {t('admin.tabs.sites')}
          </TabsTrigger>
          <TabsTrigger value="users">
            <Users size={16} aria-hidden="true" />
            {t('admin.tabs.users')}
          </TabsTrigger>
          <TabsTrigger value="storage">
            <HardDrives size={16} aria-hidden="true" />
            {t('admin.tabs.storage')}
          </TabsTrigger>
          <TabsTrigger value="retention">
            <ShieldWarning size={16} aria-hidden="true" />
            {t('admin.tabs.retention')}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="sites">
          <SitesTab />
        </TabsContent>
        <TabsContent value="users">
          <UsersTab />
        </TabsContent>
        <TabsContent value="storage">
          <StorageTab />
        </TabsContent>
        <TabsContent value="retention">
          <RetentionTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
