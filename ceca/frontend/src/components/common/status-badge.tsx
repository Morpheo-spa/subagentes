import {
  ArrowUUpLeft,
  CheckCircle,
  Clock,
  ImageBroken,
  PencilSimple,
  Prohibit,
  SealCheck,
  Spinner,
  WarningCircle,
  type Icon,
} from '@phosphor-icons/react'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { useI18n } from '@/lib/i18n'
import { isExpiringSoon } from '@/lib/format'
import type { ComplianceStatus, DocumentStatus } from '@/lib/types'

interface StatusVisual {
  icon: Icon
  variant: NonNullable<BadgeProps['variant']>
  key: string
  spin?: boolean
}

/**
 * MASTER §3: color + icono + texto. Nunca solo color.
 * Los estados son los de `DocumentStatus` en `app/models/documents.py`.
 */
const STATUS_VISUALS: Record<DocumentStatus, StatusVisual> = {
  pending: { icon: Spinner, variant: 'neutral', key: 'status.pending', spin: true },
  processing: { icon: Spinner, variant: 'neutral', key: 'status.processing', spin: true },
  ready: { icon: CheckCircle, variant: 'success', key: 'status.ready' },
  withdrawn: { icon: Prohibit, variant: 'destructive', key: 'status.withdrawn' },
  failed: { icon: WarningCircle, variant: 'destructive', key: 'status.failed' },
}

export function StatusBadge({
  status,
  expiresAt,
}: {
  status: DocumentStatus
  expiresAt?: string | null
}) {
  const { t } = useI18n()
  const visual = STATUS_VISUALS[status]
  const IconComponent = visual.icon

  // "Caduca en < 30 d" gana visualmente sobre "Listo" (documents.md).
  if (status === 'ready' && isExpiringSoon(expiresAt)) {
    return (
      <Badge variant="warning">
        <Clock size={14} aria-hidden="true" />
        {t('status.expiringSoon')}
      </Badge>
    )
  }

  return (
    <Badge variant={visual.variant}>
      <IconComponent
        size={14}
        aria-hidden="true"
        className={visual.spin ? 'estampa-spin' : undefined}
      />
      {t(visual.key)}
    </Badge>
  )
}

/** `ComplianceStatus`: responde a "¿sirve como documento de control?". */
const COMPLIANCE_VISUALS: Record<ComplianceStatus, StatusVisual> = {
  compliant: { icon: SealCheck, variant: 'success', key: 'compliance.compliant' },
  incomplete: { icon: PencilSimple, variant: 'warning', key: 'compliance.incomplete' },
  not_a_deca: { icon: ImageBroken, variant: 'destructive', key: 'compliance.not_a_deca' },
  superseded: { icon: ArrowUUpLeft, variant: 'neutral', key: 'compliance.superseded' },
}

/** docs/DECA.md §1: un escaneo NO es un DeCA valido y la UI lo dice. */
export function ComplianceBadge({ status }: { status: ComplianceStatus }) {
  const { t } = useI18n()
  const visual = COMPLIANCE_VISUALS[status]
  const IconComponent = visual.icon
  return (
    <Badge variant={visual.variant}>
      <IconComponent size={14} aria-hidden="true" />
      {t(visual.key)}
    </Badge>
  )
}
