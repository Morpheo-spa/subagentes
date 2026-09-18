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
import { ApiError, request } from '@/lib/api'
import { formatBytes, formatDate, formatMoney, formatNumber } from '@/lib/format'
import { useSessionPermissions } from '@/lib/auth'
import { useI18n } from '@/lib/i18n'
import { hasPermission, PERMISSIONS } from '@/lib/permissions'
import * as routes from '@/lib/routes'
import type {
  CheckoutSessionResponse,
  PlansResponse,
  SubscriptionResponse,
  UsageResponse,
} from '@/lib/types'

/** Clave del limite mensual de documentos en `plan.limits` (seed 0002). */
const DOCUMENTS_LIMIT = 'documents_per_month'

function limitOf(limits: Record<string, number | string | null>, key: string): number | null {
  const value = limits[key]
  return typeof value === 'number' ? value : null
}

/**
 * billing.md / CLAUDE.md: Stripe es desactivable (`BILLING_ENABLED`).
 * Las tres respuestas traen `enabled`; si viene a false esto NO revienta: lo
 * dice y oculta cualquier CTA de pago.
 */
export default function BillingPage() {
  const { t, locale, pick } = useI18n()
  const session = useSessionPermissions()
  const canManage = hasPermission(session, PERMISSIONS.billingManage)

  const plans = useQuery({
    queryKey: ['billing', 'plans'],
    queryFn: () => request<PlansResponse>(routes.billingPlans()),
  })
  const subscription = useQuery({
    queryKey: ['billing', 'subscription'],
    queryFn: () => request<SubscriptionResponse>(routes.billingSubscription()),
  })
  const usage = useQuery({
    queryKey: ['billing', 'usage'],
    queryFn: () => request<UsageResponse>(routes.billingUsage()),
  })

  const checkout = useMutation({
    mutationFn: (planCode: string) =>
      request<CheckoutSessionResponse>(routes.billingCheckout(), {
        body: { plan_code: planCode },
      }),
    onSuccess: (result) => {
      window.location.assign(result.url)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : t('errors.unexpected')),
  })

  if (plans.isPending || subscription.isPending || usage.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (plans.isError) return <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
  if (usage.isError) return <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
  if (subscription.isError) {
    return <ErrorState error={subscription.error} onRetry={() => void subscription.refetch()} />
  }

  if (!plans.data.enabled) {
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

  const current = subscription.data.subscription
  const included = limitOf(usage.data.limits, DOCUMENTS_LIMIT)
  const usedPercent =
    included && included > 0
      ? Math.min(100, Math.round((usage.data.documents_uploaded / included) * 100))
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
            {t('billing.periodLabel', { period: usage.data.period })}
          </p>
          <Progress value={usedPercent} aria-label={t('billing.usage')} />
          <p className="text-sm">
            {included !== null
              ? t('billing.documentsUsed', {
                  used: formatNumber(usage.data.documents_uploaded, locale),
                  included: formatNumber(included, locale),
                })
              : t('billing.documentsUsedNoLimit', {
                  used: formatNumber(usage.data.documents_uploaded, locale),
                })}
          </p>
          <p className="text-sm text-muted-foreground">
            {t('billing.labelsPrinted', {
              count: formatNumber(usage.data.labels_printed, locale),
            })}
          </p>
          <p className="text-sm text-muted-foreground">
            {t('billing.storageUsed', { size: formatBytes(usage.data.bytes_stored, locale) })}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('billing.subscription')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {current ? (
            <>
              <p className="flex items-center gap-2">
                <Badge variant={current.status === 'active' ? 'success' : 'warning'}>
                  <CreditCard size={14} aria-hidden="true" />
                  {t(`billing.statuses.${current.status}`)}
                </Badge>
                <span className="font-medium">{current.plan_code}</span>
              </p>
              {current.current_period_end ? (
                <p className="text-sm text-muted-foreground">
                  {current.cancel_at_period_end
                    ? t('billing.cancelsOn', {
                        date: formatDate(current.current_period_end, locale),
                      })
                    : t('billing.renewsOn', {
                        date: formatDate(current.current_period_end, locale),
                      })}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t('billing.noSubscription')}</p>
          )}
        </CardContent>
      </Card>

      <section aria-label={t('billing.plans')} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {[...plans.data.items]
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((plan) => (
            <Card key={plan.code}>
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
                {/* El plan trae `limits`, no una lista de textos comerciales. */}
                <dl className="flex flex-col gap-1 text-sm text-muted-foreground">
                  {Object.entries(plan.limits).map(([key, value]) => {
                    const labelKey = `billing.limits.${key}`
                    const label = t(labelKey)
                    return (
                      <div key={key} className="flex justify-between gap-2">
                        {/* Un limite que el catalogo estrene se ve, no se oculta. */}
                        <dt>
                          {label === labelKey ? <code className="estampa-mono">{key}</code> : label}
                        </dt>
                        <dd className="font-medium">
                          {typeof value === 'number' ? formatNumber(value, locale) : String(value)}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
                {canManage ? (
                  <Button
                    disabled={checkout.isPending || current?.plan_code === plan.code}
                    onClick={() => checkout.mutate(plan.code)}
                  >
                    {current?.plan_code === plan.code
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
