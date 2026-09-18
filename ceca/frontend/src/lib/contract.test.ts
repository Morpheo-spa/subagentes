/**
 * Contrato con el backend, contrastado contra su OpenAPI real.
 *
 * `openapi.snapshot.json` es lo que `app.openapi()` devuelve HOY. Se regenera
 * con `npm run contract:snapshot` cada vez que cambia el backend (README).
 *
 * No es un validador de payloads. Comprueba tres cosas y falla nombrando la
 * ruta, o el campo y el schema:
 *  (a) cada ruta de `routes.ts` existe en el backend con ese metodo;
 *  (b) cada campo que el frontend tipa en `types.ts` existe en el schema del
 *      backend con ese nombre (claves de `properties`);
 *  (c) los enumerados que la UI pinta (estados, origenes...) son los mismos.
 */
import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from './api'
import snapshot from './openapi.snapshot.json'
import { declaredRoutes, type RouteBase } from './routes'
import type {
  Acknowledgement,
  BillingProvider,
  CheckoutSessionResponse,
  ComplianceStatus,
  DecaCatalogResponse,
  DecaFieldErrorRead,
  DecaFieldRead,
  DecaStatus,
  DecaValidationResult,
  DocumentHistoryResponse,
  DocumentOrigin,
  DocumentRead,
  DocumentStatus,
  DocumentSummary,
  ErrorDetail,
  LabelTemplateCatalogResponse,
  LabelTemplateRead,
  MembershipRead,
  MembershipSummary,
  MeResponse,
  PageResponse,
  PlanRead,
  PlansResponse,
  PortalSessionResponse,
  PrintEntry,
  PrintJobItemRead,
  PrintJobRead,
  PrintJobStatus,
  PrintLayout,
  PublicAccessEntry,
  PublicDocumentView,
  QueueItemRead,
  RetentionAction,
  RetentionPolicyRead,
  RevisionEntry,
  RoleCatalogResponse,
  RoleRead,
  SessionResponse,
  SiteRead,
  SiteSummary,
  StorageBackendRead,
  StorageKind,
  StorageTestResult,
  SubscriptionRead,
  SubscriptionResponse,
  SubscriptionStatus,
  TokenPair,
  UpcomingExpiryItem,
  UploadItemResult,
  UploadResponse,
  UploadWarning,
  UsageResponse,
  UserRead,
  UserSummary,
} from './types'

interface SchemaObject {
  properties?: Record<string, unknown>
  required?: string[]
  enum?: string[]
}

interface OpenApiDocument {
  paths: Record<string, Record<string, unknown>>
  components: { schemas: Record<string, SchemaObject> }
}

const spec = snapshot as unknown as OpenApiDocument

const BASES: Record<RouteBase, string> = { api: API_BASE_URL, root: '' }

/** `{document_id}` (backend) y `{documentId}` (cliente) son el mismo marcador. */
const wildcard = (path: string) => path.replace(/\{\w+\}/g, '{}')

const backendOperations = new Set(
  Object.entries(spec.paths).flatMap(([path, operations]) =>
    Object.keys(operations).map((method) => `${method.toUpperCase()} ${wildcard(path)}`),
  ),
)

/**
 * Los nombres de campo de una interfaz, exigidos por el compilador: un
 * `Record<keyof T, true>` literal no admite ni una clave de mas ni una de
 * menos, asi que esta lista no puede desviarse de `types.ts` sin que `tsc`
 * lo diga. Lo que aqui se enumera es, exactamente, lo que el frontend lee.
 */
function fieldsOf<T extends object>(shape: Record<keyof T, true>): string[] {
  return Object.keys(shape)
}

function valuesOf<T extends string>(shape: Record<T, true>): string[] {
  return Object.keys(shape)
}

interface ResponseContract {
  /** Nombre del schema en `components.schemas` del snapshot. */
  schema: string
  fields: string[]
}

const RESPONSES: ResponseContract[] = [
  /* auth.py */
  {
    schema: 'TokenPair',
    fields: fieldsOf<TokenPair>({ access_token: true, token_type: true, expires_in: true }),
  },
  {
    schema: 'SiteSummary',
    fields: fieldsOf<SiteSummary>({
      id: true,
      name: true,
      site_prefix: true,
      timezone: true,
      is_active: true,
    }),
  },
  {
    schema: 'UserSummary',
    fields: fieldsOf<UserSummary>({
      id: true,
      email: true,
      full_name: true,
      locale: true,
      is_superuser: true,
      default_site_id: true,
    }),
  },
  {
    schema: 'MembershipSummary',
    fields: fieldsOf<MembershipSummary>({ site: true, role: true, permissions: true }),
  },
  {
    schema: 'SessionResponse',
    fields: fieldsOf<SessionResponse>({ tokens: true, user: true, site: true, permissions: true }),
  },
  {
    schema: 'MeResponse',
    fields: fieldsOf<MeResponse>({
      user: true,
      site: true,
      permissions: true,
      sites: true,
      locale: true,
    }),
  },

  /* common.py */
  {
    schema: 'PageResponse_DocumentSummary_',
    fields: fieldsOf<PageResponse<DocumentSummary>>({
      items: true,
      total: true,
      page: true,
      page_size: true,
    }),
  },
  { schema: 'Acknowledgement', fields: fieldsOf<Acknowledgement>({ ok: true, code: true }) },
  {
    schema: 'ErrorDetail',
    fields: fieldsOf<ErrorDetail>({ code: true, message: true, params: true }),
  },

  /* documents.py */
  {
    schema: 'DocumentSummary',
    fields: fieldsOf<DocumentSummary>({
      id: true,
      original_filename: true,
      status: true,
      deca_status: true,
      origin: true,
      compliance_status: true,
      is_valid_deca: true,
      revision: true,
      byte_size: true,
      page_count: true,
      print_count: true,
      created_at: true,
      expires_at: true,
      withdrawn_at: true,
      superseded_at: true,
    }),
  },
  {
    schema: 'DocumentRead',
    fields: fieldsOf<DocumentRead>({
      id: true,
      original_filename: true,
      status: true,
      deca_status: true,
      origin: true,
      compliance_status: true,
      is_valid_deca: true,
      revision: true,
      byte_size: true,
      page_count: true,
      print_count: true,
      created_at: true,
      expires_at: true,
      withdrawn_at: true,
      superseded_at: true,
      sha256: true,
      has_text_layer: true,
      qr_embedded: true,
      deca: true,
      deca_catalog_version: true,
      supersedes_id: true,
      change_reason: true,
      withdrawn_reason: true,
      failure_code: true,
      uploaded_by_id: true,
      retention_policy_id: true,
      storage_backend_id: true,
      updated_at: true,
      version: true,
      share_token: true,
      public_url: true,
    }),
  },
  { schema: 'UploadWarning', fields: fieldsOf<UploadWarning>({ code: true, params: true }) },
  {
    schema: 'UploadItemResult',
    fields: fieldsOf<UploadItemResult>({
      filename: true,
      accepted: true,
      document: true,
      warnings: true,
      error: true,
    }),
  },
  {
    schema: 'UploadResponse',
    fields: fieldsOf<UploadResponse>({ items: true, accepted: true, rejected: true }),
  },
  {
    schema: 'RevisionEntry',
    fields: fieldsOf<RevisionEntry>({
      id: true,
      revision: true,
      change_reason: true,
      created_at: true,
      superseded_at: true,
      is_current: true,
    }),
  },
  {
    schema: 'PrintEntry',
    fields: fieldsOf<PrintEntry>({
      print_job_id: true,
      copies: true,
      template_code: true,
      printed_at: true,
      user_id: true,
    }),
  },
  {
    schema: 'PublicAccessEntry',
    fields: fieldsOf<PublicAccessEntry>({ accessed_at: true, ip_hash: true, user_agent: true }),
  },
  {
    schema: 'DocumentHistoryResponse',
    fields: fieldsOf<DocumentHistoryResponse>({
      document_id: true,
      revisions: true,
      prints: true,
      public_accesses: true,
    }),
  },
  {
    schema: 'PublicDocumentView',
    fields: fieldsOf<PublicDocumentView>({
      original_filename: true,
      issued_at: true,
      revision: true,
      is_valid_deca: true,
      compliance_status: true,
      deca: true,
      file_url: true,
      site_name: true,
    }),
  },

  /* deca.py */
  {
    schema: 'DecaFieldRead',
    fields: fieldsOf<DecaFieldRead>({
      code: true,
      label_es: true,
      label_en: true,
      help_es: true,
      help_en: true,
      data_type: true,
      is_required: true,
      max_length: true,
      pattern: true,
      choices: true,
      legal_reference: true,
      sort_order: true,
    }),
  },
  {
    schema: 'DecaCatalogResponse',
    fields: fieldsOf<DecaCatalogResponse>({ catalog_version: true, fields: true }),
  },
  {
    schema: 'DecaFieldErrorRead',
    fields: fieldsOf<DecaFieldErrorRead>({ field: true, code: true, message: true, params: true }),
  },
  {
    schema: 'DecaValidationResult',
    fields: fieldsOf<DecaValidationResult>({
      is_complete: true,
      deca_status: true,
      catalog_version: true,
      errors: true,
    }),
  },

  /* printing.py */
  {
    schema: 'QueueItemRead',
    fields: fieldsOf<QueueItemRead>({
      id: true,
      document_id: true,
      copies: true,
      position: true,
      created_at: true,
      document: true,
    }),
  },
  {
    schema: 'LabelTemplateRead',
    fields: fieldsOf<LabelTemplateRead>({
      code: true,
      name_es: true,
      name_en: true,
      layout: true,
      columns: true,
      rows: true,
      slots_per_sheet: true,
      label_width_mm: true,
      label_height_mm: true,
    }),
  },
  {
    schema: 'LabelTemplateCatalogResponse',
    fields: fieldsOf<LabelTemplateCatalogResponse>({ items: true }),
  },
  {
    schema: 'PrintJobItemRead',
    fields: fieldsOf<PrintJobItemRead>({
      id: true,
      document_id: true,
      copies: true,
      label_index: true,
    }),
  },
  {
    schema: 'PrintJobRead',
    fields: fieldsOf<PrintJobRead>({
      id: true,
      status: true,
      template_code: true,
      layout: true,
      printer_name: true,
      start_position: true,
      label_count: true,
      page_count: true,
      confirmed_at: true,
      failure_reason: true,
      created_at: true,
      user_id: true,
      items: true,
    }),
  },

  /* billing.py */
  {
    schema: 'PlanRead',
    fields: fieldsOf<PlanRead>({
      code: true,
      name_es: true,
      name_en: true,
      price_cents: true,
      currency: true,
      interval: true,
      limits: true,
      sort_order: true,
    }),
  },
  { schema: 'PlansResponse', fields: fieldsOf<PlansResponse>({ enabled: true, items: true }) },
  {
    schema: 'SubscriptionRead',
    fields: fieldsOf<SubscriptionRead>({
      plan_code: true,
      status: true,
      provider: true,
      current_period_start: true,
      current_period_end: true,
      cancel_at_period_end: true,
      limits: true,
    }),
  },
  {
    schema: 'SubscriptionResponse',
    fields: fieldsOf<SubscriptionResponse>({ enabled: true, subscription: true }),
  },
  {
    schema: 'UsageResponse',
    fields: fieldsOf<UsageResponse>({
      enabled: true,
      period: true,
      documents_uploaded: true,
      labels_printed: true,
      bytes_stored: true,
      limits: true,
    }),
  },
  {
    schema: 'CheckoutSessionResponse',
    fields: fieldsOf<CheckoutSessionResponse>({ url: true, session_id: true }),
  },
  { schema: 'PortalSessionResponse', fields: fieldsOf<PortalSessionResponse>({ url: true }) },

  /* storage.py */
  {
    schema: 'StorageBackendRead',
    fields: fieldsOf<StorageBackendRead>({
      id: true,
      name: true,
      kind: true,
      config: true,
      is_default: true,
      is_active: true,
      last_health_ok: true,
      created_at: true,
      updated_at: true,
      version: true,
    }),
  },
  {
    schema: 'StorageTestResult',
    fields: fieldsOf<StorageTestResult>({ ok: true, kind: true, checked_at: true, code: true }),
  },

  /* retention.py */
  {
    schema: 'RetentionPolicyRead',
    fields: fieldsOf<RetentionPolicyRead>({
      id: true,
      name: true,
      retention_days: true,
      action: true,
      legal_basis: true,
      warn_days_before: true,
      is_default: true,
      is_active: true,
      created_at: true,
      updated_at: true,
      version: true,
      legal_minimum_days: true,
    }),
  },
  {
    schema: 'UpcomingExpiryItem',
    fields: fieldsOf<UpcomingExpiryItem>({
      document_id: true,
      original_filename: true,
      expires_at: true,
      days_left: true,
      policy_id: true,
      policy_name: true,
      action: true,
    }),
  },

  /* tenancy.py */
  {
    schema: 'SiteRead',
    fields: fieldsOf<SiteRead>({
      id: true,
      name: true,
      site_prefix: true,
      timezone: true,
      address: true,
      is_active: true,
      created_at: true,
      updated_at: true,
    }),
  },
  {
    schema: 'MembershipRead',
    fields: fieldsOf<MembershipRead>({
      id: true,
      site_id: true,
      site_name: true,
      role: true,
      extra_permissions: true,
      permissions: true,
    }),
  },
  {
    schema: 'UserRead',
    fields: fieldsOf<UserRead>({
      id: true,
      email: true,
      full_name: true,
      is_active: true,
      is_superuser: true,
      locale: true,
      default_site_id: true,
      last_login_at: true,
      created_at: true,
      memberships: true,
    }),
  },
  { schema: 'RoleRead', fields: fieldsOf<RoleRead>({ code: true, permissions: true }) },
  {
    schema: 'RoleCatalogResponse',
    fields: fieldsOf<RoleCatalogResponse>({ roles: true, permissions: true }),
  },
]

interface EnumContract {
  schema: string
  values: string[]
}

/** Los enumerados que la UI pinta con icono y texto (`status-badge.tsx` y cia). */
const ENUMS: EnumContract[] = [
  {
    schema: 'DocumentStatus',
    values: valuesOf<DocumentStatus>({
      pending: true,
      processing: true,
      ready: true,
      withdrawn: true,
      failed: true,
    }),
  },
  {
    schema: 'DecaStatus',
    values: valuesOf<DecaStatus>({ completo: true, incompleto: true, no_aplica: true }),
  },
  {
    schema: 'DocumentOrigin',
    values: valuesOf<DocumentOrigin>({
      generated: true,
      uploaded_native: true,
      uploaded_scanned: true,
    }),
  },
  {
    schema: 'ComplianceStatus',
    values: valuesOf<ComplianceStatus>({
      compliant: true,
      incomplete: true,
      not_a_deca: true,
      superseded: true,
    }),
  },
  { schema: 'PrintLayout', values: valuesOf<PrintLayout>({ single: true, sheet: true }) },
  {
    schema: 'PrintJobStatus',
    values: valuesOf<PrintJobStatus>({ pending: true, printed: true, failed: true }),
  },
  {
    schema: 'SubscriptionStatus',
    values: valuesOf<SubscriptionStatus>({
      trialing: true,
      active: true,
      past_due: true,
      canceled: true,
      disabled: true,
    }),
  },
  { schema: 'BillingProvider', values: valuesOf<BillingProvider>({ stripe: true, manual: true }) },
  {
    schema: 'StorageKind',
    values: valuesOf<StorageKind>({
      local: true,
      s3: true,
      ftp: true,
      sftp: true,
      google_drive: true,
      onedrive: true,
    }),
  },
  {
    schema: 'RetentionAction',
    values: valuesOf<RetentionAction>({ withdraw_file: true, revoke_share: true, flag_only: true }),
  },
]

describe('contrato con el OpenAPI del backend (openapi.snapshot.json)', () => {
  it('el snapshot describe el prefijo de API que usa el cliente', () => {
    const underPrefix = [...backendOperations].filter((operation) =>
      operation.includes(` ${API_BASE_URL}/`),
    )
    expect(underPrefix.length, `ninguna ruta del snapshot cuelga de ${API_BASE_URL}`).toBeGreaterThan(0)
  })

  it('cada ruta de routes.ts existe en el backend con ese metodo', () => {
    const missing = declaredRoutes()
      .map((route) => `${route.method} ${wildcard(`${BASES[route.base]}${route.template}`)}`)
      .filter((operation) => !backendOperations.has(operation))

    expect(missing, 'rutas del cliente que el backend no sirve').toEqual([])
  })

  it('el cliente nunca hace HEAD al visor publico: cada consulta ya cuenta como acceso', () => {
    // `HEAD /v/{token}` registra un acceso igual que `GET`; comprobar y luego
    // pedir contaria cada escaneo dos veces. El tipo `HttpMethod` ya no lo admite.
    const heads = declaredRoutes().filter((route) => (route.method as string) === 'HEAD')
    expect(heads).toEqual([])
  })

  it('el refresh token no viaja en la respuesta: TokenPair sin refresh_token', () => {
    const tokenPair = spec.components.schemas.TokenPair
    expect(tokenPair).toBeDefined()
    expect(Object.keys(tokenPair?.properties ?? {})).not.toContain('refresh_token')
  })

  describe('cada campo que el frontend lee existe en el schema del backend', () => {
    it.each(RESPONSES)('$schema', ({ schema, fields }) => {
      const definition = spec.components.schemas[schema]
      expect(definition, `el schema "${schema}" no existe en el snapshot`).toBeDefined()

      const properties = Object.keys(definition?.properties ?? {})
      const missing = fields.filter((field) => !properties.includes(field))
      expect(missing, `campos que el frontend lee y "${schema}" no tiene`).toEqual([])
    })
  })

  describe('los enumerados que la UI pinta son los del backend', () => {
    it.each(ENUMS)('$schema', ({ schema, values }) => {
      const definition = spec.components.schemas[schema]
      expect(definition?.enum, `"${schema}" no es un enumerado en el snapshot`).toBeDefined()
      expect([...values].sort(), `valores de "${schema}"`).toEqual([...(definition?.enum ?? [])].sort())
    })
  })
})
