import { SignIn } from '@phosphor-icons/react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { LanguageSelect } from '@/components/common/language-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card'
import { FormField, FormLabel, useFormControlProps } from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useI18n } from '@/lib/i18n'

function Field({
  label,
  type,
  value,
  onChange,
  autoComplete,
  required,
}: {
  label: string
  type: string
  value: string
  onChange: (value: string) => void
  autoComplete: string
  required?: boolean
}) {
  const control = useFormControlProps()
  return (
    <>
      <FormLabel required={required}>{label}</FormLabel>
      <Input
        {...control}
        type={type}
        value={value}
        autoComplete={autoComplete}
        required={required}
        onChange={(event) => onChange(event.target.value)}
      />
    </>
  )
}

export default function LoginPage() {
  const { t } = useI18n()
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Al arrancar se intenta rehidratar la sesion desde la cookie: mientras
  // tanto no se ensena el formulario, que parpadearia si la sesion existe.
  if (status === 'loading') {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4" aria-busy="true">
        <Skeleton className="h-80 w-full max-w-md" />
      </main>
    )
  }

  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/'} replace />
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('errors.unexpected'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-4 py-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          {/* La unica pagina sin app shell: el titulo de la tarjeta es el h1. */}
          <h1 className="text-lead font-semibold">{t('auth.title')}</h1>
          <CardDescription>{t('auth.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
            <FormField>
              <Field
                label={t('auth.email')}
                type="email"
                value={email}
                onChange={setEmail}
                autoComplete="username"
                required
              />
            </FormField>
            <FormField error={error}>
              <Field
                label={t('auth.password')}
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete="current-password"
                required
              />
            </FormField>
            <Button type="submit" disabled={busy}>
              <SignIn size={20} aria-hidden="true" />
              {busy ? t('auth.signingIn') : t('auth.signIn')}
            </Button>
          </form>
        </CardContent>
      </Card>
      <LanguageSelect />
    </main>
  )
}
