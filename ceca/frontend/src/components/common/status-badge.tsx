import {
  CheckCircle,
  Clock,
  Printer,
  Prohibit,
  Spinner,
  Tag,
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

/** MASTER §3: color + icono + texto. Nunca solo color. */
const STATUS_VISUALS: Record<DocumentStatus, StatusVisual> = {
  uploading: { icon: Spinner, variant: 'neutral', key: 'status.uploading', spin: true },
  processing: { icon: Spinner, variant: 'neutral', key: 'status.processing', spin: true },
  ready: { icon: CheckCircle, variant: 'success', key: 'status.ready' },
  queued: { icon: Printer, variant: 'secondary', key: 'status.queued' },
  printed: { icon: Tag, variant: 'primary', key: 'status.printed' },
  withdrawn: { icon: Prohibit, variant: 'destructive', key: 'status.withdrawn' },
  error: { icon: WarningCircle, variant: 'destructive', key: 'status.error' },
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

const COMPLIANCE_VISUALS: Record<ComplianceStatus, StatusVisual> = {
  DECA_OK: { icon: CheckCircle, variant: 'success', key: 'compliance.ok' },
  DECA_INCOMPLETE: { icon: Clock, variant: 'warning', key: 'compliance.incomplete' },
  NOT_A_DECA: { icon: Prohibit, variant: 'destructive', key: 'compliance.notADeca' },
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
