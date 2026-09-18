import {
  Buildings,
  CaretDown,
  CreditCard,
  FileText,
  Gear,
  List,
  Printer,
  SignOut,
  SidebarSimple,
  UploadSimple,
  User,
  type Icon,
} from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LanguageSelect } from '@/components/common/language-select'
import { ThemeSelect } from '@/components/common/theme-select'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { toast } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api'
import { useAuth, useSessionPermissions } from '@/lib/auth'
import { useI18n } from '@/lib/i18n'
import { hasPermission, PERMISSIONS, type Permission } from '@/lib/permissions'
import { cn } from '@/lib/utils'

interface NavEntry {
  to: string
  labelKey: string
  icon: Icon
  permission?: Permission
}

/** Orden del menu = orden de aterrizaje: la primera entrada permitida es la home. */
export const NAV: NavEntry[] = [
  { to: '/upload', labelKey: 'nav.upload', icon: UploadSimple, permission: PERMISSIONS.documentsCreate },
  { to: '/deca/new', labelKey: 'nav.deca', icon: FileText, permission: PERMISSIONS.documentsCreate },
  { to: '/documents', labelKey: 'nav.documents', icon: FileText, permission: PERMISSIONS.documentsRead },
  { to: '/printing', labelKey: 'nav.printing', icon: Printer, permission: PERMISSIONS.printingRead },
  { to: '/billing', labelKey: 'nav.billing', icon: CreditCard, permission: PERMISSIONS.billingRead },
  { to: '/admin', labelKey: 'nav.admin', icon: Gear, permission: PERMISSIONS.usersRead },
]

const COLLAPSE_KEY = 'estampa.sidebar.collapsed'

function useCollapsed() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* preferencia no persistible */
    }
  }, [collapsed])
  return [collapsed, setCollapsed] as const
}

function NavList({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { t } = useI18n()
  const session = useSessionPermissions()
  const entries = NAV.filter((entry) => !entry.permission || hasPermission(session, entry.permission))

  return (
    <ul className="flex flex-col gap-1">
      {entries.map((entry) => {
        const IconComponent = entry.icon
        const label = t(entry.labelKey)
        return (
          <li key={entry.to}>
            <NavLink
              to={entry.to}
              onClick={onNavigate}
              aria-label={collapsed ? label : undefined}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150 ease-out',
                  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                  collapsed && 'justify-center px-0',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-foreground hover:bg-muted',
                )
              }
            >
              <IconComponent size={24} aria-hidden="true" className="shrink-0" />
              {collapsed ? null : <span>{label}</span>}
            </NavLink>
          </li>
        )
      })}
    </ul>
  )
}

function SiteSwitcher() {
  const { site, sites, switchSite } = useAuth()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)

  if (!site) return null

  const change = async (siteId: string) => {
    if (siteId === site.id) return
    setBusy(true)
    try {
      await switchSite(siteId)
      // Todo lo cacheado era del centro anterior: documentos, cola, historico.
      // Sin esto la lista seguia ensenando el otro centro hasta recargar.
      await queryClient.invalidateQueries()
      toast.success(t('shell.siteChanged'))
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('errors.unexpected')
      toast.error(message)
    } finally {
      setBusy(false)
    }
  }

  // En movil el selector se queda con el ancho que sobra (y trunca); a partir
  // de `sm` mide lo de siempre. Un ancho fijo desbordaba la barra en 375px.
  return (
    <div className="min-w-0 flex-1 sm:w-56 sm:flex-none">
      <Select value={site.id} disabled={busy} onValueChange={(value) => void change(value)}>
        <SelectTrigger
          className="h-9 w-full min-w-0 gap-2 text-sm [&>span]:min-w-0"
          aria-label={t('shell.site')}
        >
          <Buildings size={16} aria-hidden="true" className="hidden shrink-0 sm:block" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {/* `/auth/me` es lo unico que lista los sites del usuario. */}
          {(sites.length > 0 ? sites.map((membership) => membership.site) : [site]).map((entry) => (
            <SelectItem key={entry.id} value={entry.id}>
              {entry.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  if (!user) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2 px-2 sm:px-3">
          <User size={16} aria-hidden="true" />
          <span className="hidden max-w-32 truncate sm:inline">{user.full_name}</span>
          <CaretDown size={16} aria-hidden="true" className="hidden sm:inline" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            void logout().then(() => {
              // Nada del usuario anterior se queda en cache para el siguiente.
              queryClient.clear()
              navigate('/login', { replace: true })
            })
          }}
        >
          <SignOut size={16} aria-hidden="true" />
          {t('shell.logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Sidebar 240px colapsable + topbar 56px (MASTER §5). */
export function AppShell() {
  const { t } = useI18n()
  const [collapsed, setCollapsed] = useCollapsed()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-dvh bg-background">
      <a
        href="#estampa-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
      >
        {t('shell.skipToContent')}
      </a>

      <header
        className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-card px-4"
        style={{ height: 'var(--shell-topbar)' }}
      >
        <Button
          variant="ghost"
          size="iconSm"
          className="lg:hidden"
          aria-label={t('shell.openMenu')}
          onClick={() => setMobileOpen(true)}
        >
          <List size={16} aria-hidden="true" />
        </Button>
        <Button
          variant="ghost"
          size="iconSm"
          className="hidden lg:inline-flex"
          aria-label={collapsed ? t('shell.expandSidebar') : t('shell.collapseSidebar')}
          aria-pressed={collapsed}
          onClick={() => setCollapsed(!collapsed)}
        >
          <SidebarSimple size={16} aria-hidden="true" />
        </Button>
        {/* En movil manda el selector de centro (MASTER §5); la marca cede el sitio. */}
        <span className="hidden shrink-0 font-bold tracking-tight sm:inline">{t('app.name')}</span>
        <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1 sm:gap-2">
          <SiteSwitcher />
          {/* El idioma se queda en el cliente: no hay endpoint con el que un
              usuario cambie su propio `locale` (`PATCH /users/{id}` es de
              `users:manage`, y `/auth/me` es solo de lectura). */}
          <LanguageSelect compact />
          <ThemeSelect />
          <UserMenu />
        </div>
      </header>

      <div className="flex">
        <nav
          aria-label={t('shell.mainNav')}
          className="sticky hidden shrink-0 border-r border-border bg-card p-3 lg:block"
          style={{
            top: 'var(--shell-topbar)',
            height: 'calc(100dvh - var(--shell-topbar))',
            width: collapsed ? 'var(--shell-sidebar-collapsed)' : 'var(--shell-sidebar)',
          }}
        >
          <NavList collapsed={collapsed} />
        </nav>

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" closeLabel={t('common.close')} className="max-w-72">
            <SheetTitle>{t('shell.mainNav')}</SheetTitle>
            <NavList collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        <main id="estampa-main" className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-[var(--content-max)] px-4 py-6 md:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
