/**
 * Sesion de Estampa.
 *
 * Los dos tokens viven SOLO en memoria (refs de React, nunca `localStorage`,
 * `sessionStorage` ni `window.*`): CLAUDE.md §3.6.
 *
 * Consecuencia honesta: `POST /auth/refresh` pide el refresh token en el cuerpo
 * (`RefreshRequest`) y el backend no emite ninguna cookie httpOnly, asi que al
 * recargar la pagina no hay nada con lo que rehidratar y toca volver a entrar.
 * La alternativa seria guardarlo en el navegador, que es justo lo prohibido.
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
import { request, setAuthBridge } from './api'
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
  status: 'loading' | 'authenticated' | 'anonymous'
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  switchSite: (siteId: string) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // Tokens en memoria. Deliberadamente refs: no se serializan ni se persisten.
  const accessRef = useRef<string | null>(null)
  const refreshRef = useRef<string | null>(null)

  const [user, setUser] = useState<UserSummary | null>(null)
  const [site, setSite] = useState<SiteSummary | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [sites, setSites] = useState<MembershipSummary[]>([])
  const [status, setStatus] = useState<AuthValue['status']>('anonymous')

  const clearSession = useCallback(() => {
    accessRef.current = null
    refreshRef.current = null
    setUser(null)
    setSite(null)
    setPermissions([])
    setSites([])
    setStatus('anonymous')
  }, [])

  const adopt = useCallback((session: SessionResponse) => {
    accessRef.current = session.tokens.access_token
    refreshRef.current = session.tokens.refresh_token
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

  // Puente con el cliente HTTP: le damos el token y el refresh, no al reves.
  useEffect(() => {
    setAuthBridge({
      getToken: () => accessRef.current,
      refresh: async () => {
        const token = refreshRef.current
        if (!token) return null
        try {
          const session = await request<SessionResponse>(routes.authRefresh(), {
            body: { refresh_token: token },
            skipAuth: true,
          })
          adopt(session)
          return session.tokens.access_token
        } catch {
          return null
        }
      },
      onAuthFailure: clearSession,
    })
    return () => setAuthBridge(null)
  }, [adopt, clearSession])

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
    const token = refreshRef.current
    try {
      await request(routes.authLogout(), { body: { refresh_token: token } })
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
