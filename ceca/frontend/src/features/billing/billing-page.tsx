import { useMutation, useQuery } from '@tanstack/react-query'
import { CreditCard, Info } from '@phosphor-icons/react'
import { ErrorState } from '@/components/common/error-state'
import { EmptyState } from '@/components/common/empty-state'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { api, ApiError } from '@/lib/api'
import { formatBytes, formatDate, formatMoney, formatNumber } from '@/lib/format'
import { useAuth } from '@/lib/auth'
import { useI18n } from '@/lib/i18n'
import { hasPermission, PERMISSIONS } from '@/lib/permissions'
import type { BillingResponse } from '@/lib/types'

/**
 * billing.md / CLAUDE.md: Stripe es desactivable (`BILLING_ENABLED`).
 * Si la API responde `{"enabled": false}` esto NO revienta: lo dice y oculta
 * cualquier CTA de pago.
 */
export default function BillingPage() {
  const { t, locale, pick } = useI18n()
  const { user } = useAuth()
  const canManage = hasPermission(user, PERMISSIONS.billingManage)

  const billing = useQuery({
    queryKey: ['billing'],
    queryFn: () => api.get<BillingResponse>('/billing'),
  })

  const checkout = useMutation({
    mutationFn: (planCode: string) =>
      api.post<{ url: string }>('/billing/checkout', { plan_code: planCode }),
    onSuccess: (result) => {
      window.location.assign(result.url)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  if (billing.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (billing.isError) return <ErrorState error={billing.error} onRetry={() => void billing.refetch()} />

  if (!billing.data.enabled) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={t('billing.title')} />
        <EmptyState
          icon={Info}
          title={t('billing.disabledTitle')}
          description={t('billing.disabledBody')}
        />
      </div>
    )
  }

  const { plans, subscription, usage } = billing.data
  const usedPercent =
    usage.documents_included > 0
      ? Math.min(100, Math.round((usage.documents_used / usage.documents_included) * 100))
      : 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('billing.title')} description={t('billing.subtitle')} />

      <Card>
        <CardHeader>
          <CardTitle>{t('billing.usage')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {t('billing.period', {
              from: formatDate(usage.period_start, locale),
              to: formatDate(usage.period_end, locale),
            })}
          </p>
          <Progress value={usedPercent} aria-label={t('billing.usage')} />
          <p className="text-sm">
            {t('billing.documentsUsed', {
              used: formatNumber(usage.documents_used, locale),
              included: formatNumber(usage.documents_included, locale),
            })}
          </p>
          <p className="text-sm text-muted-foreground">
            {t('billing.storageUsed', { size: formatBytes(usage.storage_bytes, locale) })}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('billing.subscription')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {subscription ? (
            <>
              <p className="flex items-center gap-2">
                <Badge variant={subscription.status === 'active' ? 'success' : 'warning'}>
                  <CreditCard size={14} aria-hidden="true" />
                  {t(`billing.statuses.${subscription.status}`)}
                </Badge>
                <span className="font-medium">{subscription.plan_code}</span>
              </p>
              {subscription.renews_at ? (
                <p className="text-sm text-muted-foreground">
                  {subscription.cancel_at_period_end
                    ? t('billing.cancelsOn', { date: formatDate(subscription.renews_at, locale) })
                    : t('billing.renewsOn', { date: formatDate(subscription.renews_at, locale) })}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t('billing.noSubscription')}</p>
          )}
        </CardContent>
      </Card>

      <section aria-label={t('billing.plans')} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {plans.map((plan) => (
          <Card key={plan.id}>
            <CardHeader>
              <CardTitle>{pick(plan, 'name')}</CardTitle>
              <p className="text-h2 font-bold">
                {formatMoney(plan.price_cents, plan.currency, locale)}
                <span className="text-sm font-normal text-muted-foreground">
                  {' '}
                  / {t(`billing.intervals.${plan.interval}`)}
                </span>
              </p>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <ul className="flex list-inside list-disc flex-col gap-1 text-sm text-muted-foreground">
                {(locale === 'es' ? plan.features_es : plan.features_en).map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              {canManage ? (
                <Button
                  disabled={checkout.isPending || subscription?.plan_code === plan.code}
                  onClick={() => checkout.mutate(plan.code)}
                >
                  {subscription?.plan_code === plan.code
                    ? t('billing.currentPlan')
                    : t('billing.choosePlan')}
                </Button>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  )
}
