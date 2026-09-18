/**
 * Contrato de la API, calcado de `backend/app/schemas/*.py`.
 *
 * Nada de aqui se inventa: cada interfaz tiene su gemela en el backend y los
 * nombres de campo son los que viajan por el cable (`original_filename`, no
 * `original_name`). Si el backend cambia, se cambia aqui.
 */

export type Locale = 'es' | 'en'

/* ---- common.py ------------------------------------------------------- */

/** `PageResponse[ItemT]`: la unica forma que devuelve una coleccion. */
export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Acknowledgement {
  ok: boolean
  code: string | null
}

export interface ErrorDetail {
  code: string
  message: string
  params: Record<string, unknown>
}

export interface PageParams {
  page: number
  page_size: number
}

/* ---- auth.py --------------------------------------------------------- */

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface SiteSummary {
  id: string
  name: string
  site_prefix: string
  timezone: string
  is_active: boolean
}

export interface UserSummary {
  id: string
  email: string
  full_name: string
  locale: string
  is_superuser: boolean
  default_site_id: string | null
}

export interface MembershipSummary {
  site: SiteSummary
  role: string
  permissions: string[]
}

/** Respuesta de login, refresh y switch-site. */
export interface SessionResponse {
  tokens: TokenPair
  user: UserSummary
  site: SiteSummary
  permissions: string[]
}

export interface MeResponse {
  user: UserSummary
  site: SiteSummary
  permissions: string[]
  sites: MembershipSummary[]
  locale: string
}

/* ---- documents.py ---------------------------------------------------- */

export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'withdrawn' | 'failed'

export type DecaStatus = 'completo' | 'incompleto' | 'no_aplica'

/** Un escaneo (`uploaded_scanned`) nunca es un DeCA valido (docs/DECA.md §1). */
export type DocumentOrigin = 'generated' | 'uploaded_native' | 'uploaded_scanned'

export type ComplianceStatus = 'compliant' | 'incomplete' | 'not_a_deca' | 'superseded'

/** El contenido DeCA es un diccionario libre: el catalogo dice que hay dentro. */
export type DecaData = Record<string, string | number | boolean | null>

export interface DocumentSummary {
  id: string
  original_filename: string
  status: DocumentStatus
  deca_status: DecaStatus
  origin: DocumentOrigin
  compliance_status: ComplianceStatus
  is_valid_deca: boolean
  revision: number
  byte_size: number
  page_count: number | null
  print_count: number
  created_at: string
  expires_at: string | null
  withdrawn_at: string | null
  superseded_at: string | null
}

/** Detalle. Ni claves de storage ni credenciales aparecen aqui. */
export interface DocumentRead extends DocumentSummary {
  sha256: string | null
  has_text_layer: boolean | null
  qr_embedded: boolean
  deca: DecaData
  deca_catalog_version: number | null
  supersedes_id: string | null
  change_reason: string | null
  withdrawn_reason: string | null
  failure_code: string | null
  uploaded_by_id: string | null
  retention_policy_id: string | null
  storage_backend_id: string
  updated_at: string
  version: number
  share_token: string | null
  public_url: string | null
}

/** Duplicado o escaneo: el fichero se archiva y decide el usuario. */
export interface UploadWarning {
  code: string
  params: Record<string, unknown>
}

export const WARNING_DUPLICATE = 'DUPLICATE_DOCUMENT'
export const WARNING_SCAN = 'DOCUMENT_IS_A_SCAN'

/** Una entrada por fichero enviado: un fichero malo no tumba la tanda. */
export interface UploadItemResult {
  filename: string
  accepted: boolean
  document: DocumentSummary | null
  warnings: UploadWarning[]
  error: ErrorDetail | null
}

export interface UploadResponse {
  items: UploadItemResult[]
  accepted: number
  rejected: number
}

/** Filtros de `GET /documents/`. No hay `sort` ni `order`: el backend no los toma. */
export interface DocumentFilters {
  search?: string
  status?: DocumentStatus
  deca_status?: DecaStatus
  compliance_status?: ComplianceStatus
  origin?: DocumentOrigin
  created_from?: string
  created_to?: string
  expires_before?: string
  include_superseded?: boolean
}

export interface RevisionEntry {
  id: string
  revision: number
  change_reason: string | null
  created_at: string
  superseded_at: string | null
  is_current: boolean
}

export interface PrintEntry {
  print_job_id: string
  copies: number
  template_code: string
  printed_at: string | null
  user_id: string | null
}

export interface PublicAccessEntry {
  accessed_at: string
  ip_hash: string | null
  user_agent: string | null
}

export interface DocumentHistoryResponse {
  document_id: string
  revisions: RevisionEntry[]
  prints: PrintEntry[]
  public_accesses: PublicAccessEntry[]
}

/** Lo que ve quien escanea el QR. Sin identificadores internos. */
export interface PublicDocumentView {
  original_filename: string
  issued_at: string
  revision: number
  is_valid_deca: boolean
  compliance_status: ComplianceStatus
  deca: DecaData
  file_url: string
  site_name: string | null
}

/* ---- deca.py --------------------------------------------------------- */

export type DecaFieldType =
  | 'string'
  | 'text'
  | 'number'
  | 'decimal'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'enum'

/**
 * Una fila del catalogo. OJO: no trae grupo ni min/max; lo unico que ordena es
 * `sort_order`. La UI agrupa por el prefijo del `code` (ver `deca-catalog.ts`).
 */
export interface DecaFieldRead {
  code: string
  label_es: string
  label_en: string
  help_es: string | null
  help_en: string | null
  data_type: DecaFieldType
  is_required: boolean
  max_length: number | null
  pattern: string | null
  choices: string[]
  legal_reference: string | null
  sort_order: number
}

export interface DecaCatalogResponse {
  catalog_version: number
  fields: DecaFieldRead[]
}

export interface DecaFieldErrorRead {
  field: string
  code: string
  message: string
  params: Record<string, unknown>
}

/** `is_complete` es lo que decide `Document.deca_status`. */
export interface DecaValidationResult {
  is_complete: boolean
  deca_status: DecaStatus
  catalog_version: number
  errors: DecaFieldErrorRead[]
}

/* ---- printing.py ----------------------------------------------------- */

export type PrintLayout = 'single' | 'sheet'

export type PrintJobStatus = 'pending' | 'printed' | 'failed'

export interface QueueItemRead {
  id: string
  document_id: string
  copies: number
  position: number
  created_at: string
  document: DocumentSummary | null
}

/** Del catalogo del servicio: la UI nunca hardcodea una plantilla. */
export interface LabelTemplateRead {
  code: string
  name_es: string | null
  name_en: string | null
  layout: PrintLayout | null
  columns: number | null
  rows: number | null
  slots_per_sheet: number | null
  label_width_mm: number | null
  label_height_mm: number | null
}

export interface LabelTemplateCatalogResponse {
  items: LabelTemplateRead[]
}

export interface PrintJobItemRead {
  id: string
  document_id: string
  copies: number
  label_index: number
}

export interface PrintJobRead {
  id: string
  status: PrintJobStatus
  template_code: string
  layout: PrintLayout
  printer_name: string | null
  start_position: number
  label_count: number
  page_count: number
  confirmed_at: string | null
  failure_reason: string | null
  created_at: string
  user_id: string | null
  items: PrintJobItemRead[]
}

/* ---- billing.py ------------------------------------------------------ */

export type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'canceled' | 'disabled'

export type BillingProvider = 'stripe' | 'manual'

export interface PlanRead {
  code: string
  name_es: string
  name_en: string
  price_cents: number
  currency: string
  interval: string
  limits: Record<string, number | string | null>
  sort_order: number
}

export interface PlansResponse {
  enabled: boolean
  items: PlanRead[]
}

export interface SubscriptionRead {
  plan_code: string
  status: SubscriptionStatus
  provider: BillingProvider
  current_period_start: string | null
  current_period_end: string | null
  cancel_at_period_end: boolean
  limits: Record<string, number | string | null>
}

export interface SubscriptionResponse {
  enabled: boolean
  subscription: SubscriptionRead | null
}

export interface UsageResponse {
  enabled: boolean
  period: string
  documents_uploaded: number
  labels_printed: number
  bytes_stored: number
  limits: Record<string, number | string | null>
}

export interface CheckoutSessionResponse {
  url: string
  session_id: string | null
}

export interface PortalSessionResponse {
  url: string
}

/* ---- storage.py ------------------------------------------------------ */

export type StorageKind = 'local' | 's3' | 'ftp' | 'sftp' | 'google_drive' | 'onedrive'

/** No hay campo `secrets`, ni siquiera enmascarado. A proposito. */
export interface StorageBackendRead {
  id: string
  name: string
  kind: StorageKind
  config: Record<string, string | number | boolean | null>
  is_default: boolean
  is_active: boolean
  last_health_ok: boolean | null
  created_at: string
  updated_at: string
  version: number
}

export interface StorageTestResult {
  ok: boolean
  kind: StorageKind
  checked_at: string
  code: string | null
}

/* ---- retention.py ---------------------------------------------------- */

export type RetentionAction = 'withdraw_file' | 'revoke_share' | 'flag_only'

export interface RetentionPolicyRead {
  id: string
  name: string
  retention_days: number
  action: RetentionAction
  legal_basis: string | null
  warn_days_before: number
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
  version: number
  /** El minimo legal, para que la UI avise al bajar hasta el. */
  legal_minimum_days: number
}

export interface UpcomingExpiryItem {
  document_id: string
  original_filename: string
  expires_at: string
  days_left: number
  policy_id: string | null
  policy_name: string | null
  action: RetentionAction | null
}

/* ---- tenancy.py ------------------------------------------------------ */

export interface SiteRead {
  id: string
  name: string
  site_prefix: string
  timezone: string
  address: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface MembershipRead {
  id: string
  site_id: string
  site_name: string
  role: string
  extra_permissions: string[]
  permissions: string[]
}

/** Nunca lleva `hashed_password`: no existe el campo, a proposito. */
export interface UserRead {
  id: string
  email: string
  full_name: string
  is_active: boolean
  is_superuser: boolean
  locale: string
  default_site_id: string | null
  last_login_at: string | null
  created_at: string
  memberships: MembershipRead[]
}

export interface RoleRead {
  code: string
  permissions: string[]
}

/** Roles y vocabulario de permisos: la UI no los hardcodea. */
export interface RoleCatalogResponse {
  roles: RoleRead[]
  permissions: string[]
}
