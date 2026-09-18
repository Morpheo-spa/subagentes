/**
 * Sesion de Estampa.
 *
 * El access token vive SOLO en memoria (ref de React, nunca `localStorage`,
 * `sessionStorage` ni `window.*`). El refresh token no llega nunca a
 * JavaScript: el backend lo deja en la cookie HttpOnly `estampa_refresh`
 * (`app/cookies.py`, `Path=/api/v1/auth`, `SameSite=strict`) y el navegador la
 * adjunta el solo a `/auth/refresh`, `/auth/logout` y `/auth/switch-site`.
 * Por eso esas rutas van sin token en el cuerpo, y por eso la sesion SI
 * sobrevive a recargar la pagina: al arrancar se intenta `POST /auth/refresh`;
 * 200 = hay sesion, cualquier otra cosa = a login.
 *
 * `POST /auth/refresh` ademas exige que el `Origin` sea el `PUBLIC_BASE_URL`
 * del backend (403 `CROSS_ORIGIN_REJECTED`): en desarrollo, el proxy de Vite
 * (ver `vite.config.ts` y `README.md`).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ApiError, request, setAuthBridge } from './api'
import * as routes from './routes'
import type { MembershipSummary, MeResponse, SessionResponse, SiteSummary, UserSummary } from './types'

export interface AuthValue {
  user: UserSummary | null
  /** Site activo de la sesion: el backend lo fija en el token. */
  site: SiteSummary | null
  /** Permisos efectivos en el site activo. */
  permissions: string[]
  /** Sites a los que el usuario puede cambiar. */
  sites: MembershipSummary[]
  /** `loading` solo durante el arranque, mientras se rehidrata desde la cookie. */
  status: 'loading' | 'authenticated' | 'anonymous'
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  switchSite: (siteId: string) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // Access token en memoria. Deliberadamente un ref: no se serializa ni persiste.
  const accessRef = useRef<string | null>(null)
  // El arranque va una sola vez, tambien bajo StrictMode: dos refresh a la vez
  // con la misma cookie hacen que el segundo llegue con el token ya rotado.
  const bootedRef = useRef(false)

  const [user, setUser] = useState<UserSummary | null>(null)
  const [site, setSite] = useState<SiteSummary | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [sites, setSites] = useState<MembershipSummary[]>([])
  const [status, setStatus] = useState<AuthValue['status']>('loading')

  const clearSession = useCallback(() => {
    accessRef.current = null
    setUser(null)
    setSite(null)
    setPermissions([])
    setSites([])
    setStatus('anonymous')
  }, [])

  const adopt = useCallback((session: SessionResponse) => {
    accessRef.current = session.tokens.access_token
    setUser(session.user)
    setSite(session.site)
    setPermissions(session.permissions)
    setStatus('authenticated')
  }, [])

  /** La lista de sites para el selector solo la da `/auth/me`. */
  const loadMemberships = useCallback(async () => {
    try {
      const me = await request<MeResponse>(routes.authMe())
      setSites(me.sites)
    } catch {
      setSites([])
    }
  }, [])

  /**
   * `POST /auth/refresh`, sin cuerpo: el token va en la cookie. Devuelve la
   * sesion nueva (con los permisos vigentes: asi se resuelve `SESSION_STALE`)
   * o `null` si no hay sesion que rescatar.
   */
  const refreshSession = useCallback(async (): Promise<SessionResponse | null> => {
    try {
      const session = await request<SessionResponse>(routes.authRefresh(), { skipAuth: true })
      adopt(session)
      return session
    } catch (error) {
      // Un 401 es lo normal sin cookie o con ella caducada. Cualquier otra cosa
      // (403 CROSS_ORIGIN_REJECTED, USER_INACTIVE, red) se registra por codigo.
      if (import.meta.env.DEV && error instanceof ApiError && error.status !== 401) {
        console.warn(`[auth] refresh rechazado: ${error.code}`)
      }
      return null
    }
  }, [adopt])

  // Puente con el cliente HTTP: le damos el token y como refrescarlo.
  useEffect(() => {
    setAuthBridge({
      getToken: () => accessRef.current,
      refresh: async () => (await refreshSession())?.tokens.access_token ?? null,
      onAuthFailure: clearSession,
    })
    return () => setAuthBridge(null)
  }, [refreshSession, clearSession])

  // Arranque: rehidratar desde la cookie. 200 = sesion; si no, a login.
  useEffect(() => {
    if (bootedRef.current) return
    bootedRef.current = true
    void refreshSession().then(async (session) => {
      if (!session) {
        clearSession()
        return
      }
      await loadMemberships()
    })
  }, [refreshSession, clearSession, loadMemberships])

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await request<SessionResponse>(routes.authLogin(), {
        body: { email, password },
        skipAuth: true,
      })
      adopt(session)
      await loadMemberships()
    },
    [adopt, loadMemberships],
  )

  const logout = useCallback(async () => {
    try {
      // Sin cuerpo: el backend revoca el bearer y la cookie, y borra la cookie.
      await request(routes.authLogout())
    } catch {
      /* la sesion local se cierra igual */
    } finally {
      clearSession()
    }
  }, [clearSession])

  const switchSite = useCallback(
    async (siteId: string) => {
      const session = await request<SessionResponse>(routes.authSwitchSite(), {
        body: { site_id: siteId },
      })
      adopt(session)
      await loadMemberships()
    },
    [adopt, loadMemberships],
  )

  const value = useMemo<AuthValue>(
    () => ({ user, site, permissions, sites, status, login, logout, switchSite }),
    [user, site, permissions, sites, status, login, logout, switchSite],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth fuera de AuthProvider')
  return ctx
}

/** Lo que `hasPermission` necesita de la sesion activa. */
export function useSessionPermissions() {
  const { user, permissions } = useAuth()
  return user ? { is_superuser: user.is_superuser, permissions } : null
}
