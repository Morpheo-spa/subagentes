/** Tipos del contrato de la API (backend/.claude/rules/backend.md). */

export type Locale = 'es' | 'en'

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/* ---- Auth / tenancy -------------------------------------------------- */

export interface SiteRef {
  id: string
  name: string
  site_prefix: string
}

export interface CurrentUser {
  id: string
  email: string
  full_name: string
  locale: Locale | null
  is_superuser: boolean
  permissions: string[]
  mm_id: string
  site_id: string
  site_prefix: string
  sites: SiteRef[]
}

export interface LoginResponse {
  access_token: string
  expires_in: number
  user: CurrentUser
}

/* ---- Documentos ------------------------------------------------------ */

export type DocumentStatus =
  | 'uploading'
  | 'processing'
  | 'ready'
  | 'queued'
  | 'printed'
  | 'withdrawn'
  | 'error'

export type DecaStatus = 'completo' | 'incompleto'

/** Origen del fichero. Un escaneo no es un DeCA valido (docs/DECA.md §1). */
export type DocumentOrigin = 'GENERATED' | 'UPLOADED_NATIVE' | 'UPLOADED_SCANNED'

export type ComplianceStatus = 'DECA_OK' | 'DECA_INCOMPLETE' | 'NOT_A_DECA'

export interface DocumentSummary {
  id: string
  original_name: string
  status: DocumentStatus
  deca_status: DecaStatus
  origin: DocumentOrigin
  compliance_status: ComplianceStatus
  size_bytes: number
  sha256: string
  uploaded_at: string
  uploaded_by: string
  expires_at: string | null
  withdrawn_at: string | null
  withdrawn_reason: string | null
  print_count: number
  public_token: string | null
  qr_url: string | null
  revision: number
}

export interface DocumentEvent {
  id: string
  kind: 'upload' | 'print' | 'view' | 'revision' | 'withdraw' | 'revoke'
  at: string
  actor: string | null
  detail: Record<string, string | number | null>
}

export interface DocumentRevision {
  id: string
  revision: number
  created_at: string
  change_reason: string | null
  superseded: boolean
}

export interface DocumentDetail extends DocumentSummary {
  public_url: string | null
  events: DocumentEvent[]
  revisions: DocumentRevision[]
  deca_values: Record<string, string>
  retention_days: number
}

export interface DocumentListParams {
  page: number
  page_size: number
  q?: string
  status?: string
  deca_status?: string
  uploaded_from?: string
  uploaded_to?: string
  expires_before?: string
  uploaded_by?: string
  sort?: string
  order?: 'asc' | 'desc'
}

/* ---- Catalogo DeCA (nunca hardcodeado: GET /deca/fields) ------------- */

export type DecaFieldType = 'text' | 'textarea' | 'number' | 'date' | 'select' | 'nif' | 'plate'

export type DecaFieldGroup = 'cargador' | 'transportista' | 'envio' | 'mercancia' | 'otros'

export interface DecaFieldOption {
  value: string
  label_es: string
  label_en: string
}

export interface DecaFieldDefinition {
  code: string
  type: DecaFieldType
  group: DecaFieldGroup
  required: boolean
  order: number
  label_es: string
  label_en: string
  help_es: string | null
  help_en: string | null
  pattern: string | null
  min: number | null
  max: number | null
  max_length: number | null
  options: DecaFieldOption[] | null
  legal_ref: string | null
}

export interface DecaFieldCatalog {
  catalog_version: string
  fields: DecaFieldDefinition[]
}

export interface DecaFieldError {
  field: string
  code: string
  message: string
}

/* ---- Impresion ------------------------------------------------------- */

export interface PrintTemplate {
  id: string
  label_es: string
  label_en: string
  mode: 'single' | 'grid'
  columns: number
  rows: number
  page: 'A4' | 'thermal' | 'custom'
  label_width_mm: number
  label_height_mm: number
  page_width_mm: number
  page_height_mm: number
  margin_top_mm: number
  margin_left_mm: number
  gap_x_mm: number
  gap_y_mm: number
}

export interface PrinterRef {
  id: string
  name: string
}

export interface PrintQueueItem {
  id: string
  document_id: string
  original_name: string
  short_id: string
  qr_url: string | null
  public_url: string | null
  uploaded_at: string
  copies: number
  position: number
}

export interface PrintJob {
  id: string
  status: 'pending' | 'done' | 'failed'
  items: number
  copies: number
  created_at: string
}

/* ---- Facturacion ----------------------------------------------------- */

export interface BillingDisabled {
  enabled: false
}

export interface BillingPlan {
  id: string
  code: string
  name_es: string
  name_en: string
  price_cents: number
  currency: string
  interval: 'month' | 'year'
  documents_included: number
  max_upload_mb: number
  features_es: string[]
  features_en: string[]
}

export interface BillingUsage {
  period_start: string
  period_end: string
  documents_used: number
  documents_included: number
  storage_bytes: number
}

export interface BillingSubscription {
  plan_code: string
  status: 'active' | 'past_due' | 'canceled' | 'trialing'
  renews_at: string | null
  cancel_at_period_end: boolean
}

export interface BillingState {
  enabled: true
  plans: BillingPlan[]
  subscription: BillingSubscription | null
  usage: BillingUsage
}

export type BillingResponse = BillingDisabled | BillingState

/* ---- Admin ----------------------------------------------------------- */

export interface Site {
  id: string
  name: string
  site_prefix: string
  users_count: number
  created_at: string
}

export interface Role {
  code: string
  name_es: string
  name_en: string
  permissions: string[]
}

export interface AdminUser {
  id: string
  email: string
  full_name: string
  is_active: boolean
  roles: string[]
  sites: SiteRef[]
  last_login_at: string | null
}

/** Nunca incluye credenciales: el backend no las devuelve (rules/backend.md). */
export interface StorageBackend {
  id: string
  name: string
  kind: 'local' | 's3' | 'ftp'
  is_default: boolean
  health: 'ok' | 'degraded' | 'down' | 'unknown'
  last_checked_at: string | null
  /** Solo datos no sensibles (bucket, endpoint, prefijo). Jamas secretos. */
  public_config: Record<string, string>
}

export interface RetentionPolicy {
  id: string
  site_id: string
  site_name: string
  retention_days: number
  legal_minimum_days: number
  updated_at: string
}

/* ---- Visor publico --------------------------------------------------- */

export interface PublicDocument {
  original_name: string
  short_id: string
  uploaded_at: string
  tenant_name: string | null
  file_url: string
  size_bytes: number
}
