/**
 * Registro de rutas de la API.
 *
 * Es la UNICA lista de endpoints del cliente: ningun modulo escribe una ruta a
 * mano. La verdad esta en `backend/app/routers/`, y `routes.test.ts` compara
 * este registro contra esa tabla y ademas falla si alguien vuelve a colar una
 * ruta literal fuera de aqui.
 *
 * Dos bases distintas:
 *  - `api`  -> cuelga de `/api/v1` (settings.api_prefix).
 *  - `root` -> el visor publico (`public.router` se monta SIN prefijo).
 */

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD'

/** Sobre que base se resuelve la ruta. */
export type RouteBase = 'api' | 'root'

export interface ApiRoute {
  method: HttpMethod
  /** Plantilla con marcadores, tal y como la declara el backend. */
  template: string
  base: RouteBase
  /** Ruta concreta, ya sustituida. */
  path: string
}

/** Todas las rutas declaradas, en orden de declaracion. Solo lectura. */
const REGISTRY: { method: HttpMethod; template: string; base: RouteBase }[] = []

function declare(method: HttpMethod, template: string, base: RouteBase = 'api') {
  REGISTRY.push({ method, template, base })
  return (params: Record<string, string> = {}): ApiRoute => {
    const path = template.replace(/\{(\w+)\}/g, (_match, name: string) => {
      const value = params[name]
      if (value === undefined) throw new Error(`Falta el parametro "${name}" de ${template}`)
      return encodeURIComponent(value)
    })
    return { method, template, base, path }
  }
}

/** La tabla que el test contrasta contra el backend. */
export function declaredRoutes(): readonly { method: HttpMethod; template: string; base: RouteBase }[] {
  return REGISTRY
}

/* ---- auth ------------------------------------------------------------ */

export const authLogin = declare('POST', '/auth/login')
export const authRefresh = declare('POST', '/auth/refresh')
export const authLogout = declare('POST', '/auth/logout')
export const authSwitchSite = declare('POST', '/auth/switch-site')
export const authMe = declare('GET', '/auth/me')

/* ---- documentos ------------------------------------------------------ */

export const documentsList = declare('GET', '/documents/')
export const documentsUpload = declare('POST', '/documents/')
export const documentsGenerate = declare('POST', '/documents/generate')
export const documentsExportCsv = declare('GET', '/documents/export.csv')
export const documentRead = declare('GET', '/documents/{documentId}')
export const documentFile = declare('GET', '/documents/{documentId}/file')
export const documentHistory = declare('GET', '/documents/{documentId}/history')
export const documentQrPng = declare('GET', '/documents/{documentId}/qr.png')
export const documentQrSvg = declare('GET', '/documents/{documentId}/qr.svg')
export const documentPatchDeca = declare('PATCH', '/documents/{documentId}/deca')
export const documentRevisions = declare('POST', '/documents/{documentId}/revisions')
export const documentShareRevoke = declare('POST', '/documents/{documentId}/share/revoke')
export const documentWithdraw = declare('POST', '/documents/{documentId}/withdraw')

/* ---- catalogo DeCA --------------------------------------------------- */

export const decaFields = declare('GET', '/deca/fields')
export const decaValidate = declare('POST', '/deca/validate')

/* ---- impresion ------------------------------------------------------- */

export const printingQueue = declare('GET', '/printing/queue/')
export const printingQueueAdd = declare('POST', '/printing/queue/')
export const printingQueueClear = declare('DELETE', '/printing/queue/')
export const printingQueueReorder = declare('POST', '/printing/queue/reorder')
export const printingQueueItem = declare('DELETE', '/printing/queue/{itemId}')
export const printingTemplates = declare('GET', '/printing/templates')
export const printingJobs = declare('GET', '/printing/jobs/')
export const printingJobCreate = declare('POST', '/printing/jobs/')
export const printingJobRender = declare('GET', '/printing/jobs/{jobId}/render')
export const printingJobConfirm = declare('POST', '/printing/jobs/{jobId}/confirm')

/* ---- administracion -------------------------------------------------- */

export const storageList = declare('GET', '/storage/')
export const storageCreate = declare('POST', '/storage/')
export const storageRead = declare('GET', '/storage/{backendId}')
export const storageUpdate = declare('PATCH', '/storage/{backendId}')
export const storageDelete = declare('DELETE', '/storage/{backendId}')
export const storageTest = declare('POST', '/storage/{backendId}/test')

export const retentionList = declare('GET', '/retention/')
export const retentionCreate = declare('POST', '/retention/')
export const retentionUpcoming = declare('GET', '/retention/upcoming')
export const retentionRead = declare('GET', '/retention/{policyId}')
export const retentionUpdate = declare('PATCH', '/retention/{policyId}')
export const retentionDelete = declare('DELETE', '/retention/{policyId}')

export const sitesList = declare('GET', '/sites/')
export const siteCreate = declare('POST', '/sites/')
export const siteRead = declare('GET', '/sites/{siteId}')
export const siteUpdate = declare('PATCH', '/sites/{siteId}')
export const siteDelete = declare('DELETE', '/sites/{siteId}')

export const usersList = declare('GET', '/users/')
export const userCreate = declare('POST', '/users/')
export const usersRoles = declare('GET', '/users/roles')
export const userRead = declare('GET', '/users/{userId}')
export const userUpdate = declare('PATCH', '/users/{userId}')

/* ---- facturacion ----------------------------------------------------- */

export const billingPlans = declare('GET', '/billing/plans')
export const billingSubscription = declare('GET', '/billing/subscription')
export const billingUsage = declare('GET', '/billing/usage')
export const billingCheckout = declare('POST', '/billing/checkout')
export const billingPortal = declare('POST', '/billing/portal')

/* ---- visor publico (sin /api/v1) ------------------------------------- */

export const publicView = declare('GET', '/v/{token}', 'root')
export const publicFile = declare('GET', '/v/{token}/file', 'root')
