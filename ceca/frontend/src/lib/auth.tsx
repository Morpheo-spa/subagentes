/**
 * Sesion de Estampa.
 *
 * El access token vive SOLO en memoria (una ref de React, nunca `localStorage`,
 * `sessionStorage` ni `window.*`). El refresh token va en cookie httpOnly, que
 * el navegador manda solo porque `fetch` usa `credentials: 'include'`.
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
import { api, request, setAuthBridge } from './api'
import type { CurrentUser, LoginResponse, Locale } from './types'

export interface AuthValue {
  user: CurrentUser | null
  status: 'loading' | 'authenticated' | 'anonymous'
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  switchSite: (siteId: string) => Promise<void>
  updateLocale: (locale: Locale) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // Token en memoria. Deliberadamente una ref: no se serializa ni se persiste.
  const tokenRef = useRef<string | null>(null)
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [status, setStatus] = useState<AuthValue['status']>('loading')

  const clearSession = useCallback(() => {
    tokenRef.current = null
    setUser(null)
    setStatus('anonymous')
  }, [])

  // Puente con el cliente HTTP: le damos el token y el refresh, no al reves.
  useEffect(() => {
    setAuthBridge({
      getToken: () => tokenRef.current,
      refresh: async () => {
        try {
          const data = await request<LoginResponse>('/auth/refresh', {
            method: 'POST',
            skipAuth: true,
          })
          tokenRef.current = data.access_token
          setUser(data.user)
          setStatus('authenticated')
          return data.access_token
        } catch {
          return null
        }
      },
      onAuthFailure: clearSession,
    })
    return () => setAuthBridge(null)
  }, [clearSession])

  // Arranque: intentamos rehidratar con la cookie httpOnly.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await request<LoginResponse>('/auth/refresh', {
          method: 'POST',
          skipAuth: true,
        })
        if (cancelled) return
        tokenRef.current = data.access_token
        setUser(data.user)
        setStatus('authenticated')
      } catch {
        if (!cancelled) clearSession()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [clearSession])

  const login = useCallback(async (email: string, password: string) => {
    const data = await request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
      skipAuth: true,
    })
    tokenRef.current = data.access_token
    setUser(data.user)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } finally {
      clearSession()
    }
  }, [clearSession])

  const switchSite = useCallback(async (siteId: string) => {
    const data = await api.post<LoginResponse>('/auth/switch-site', { site_id: siteId })
    tokenRef.current = data.access_token
    setUser(data.user)
  }, [])

  const updateLocale = useCallback(async (locale: Locale) => {
    const updated = await api.patch<CurrentUser>('/auth/me', { locale })
    setUser(updated)
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ user, status, login, logout, switchSite, updateLocale }),
    [user, status, login, logout, switchSite, updateLocale],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth fuera de AuthProvider')
  return ctx
}
