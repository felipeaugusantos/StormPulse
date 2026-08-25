import { useEffect, useRef, useState } from 'react'
import { ApiError, login, loginWithGoogle, register } from '../api'

interface Props {
  onAuthenticated: () => void
  onVisitor: () => void
  onBack?: () => void
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID
const GOOGLE_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
const MIN_PASSWORD_LENGTH = 8

function loadGoogleScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GOOGLE_SCRIPT_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve())
      return
    }
    const script = document.createElement('script')
    script.src = GOOGLE_SCRIPT_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Falha ao carregar o script do Google'))
    document.head.appendChild(script)
  })
}

export function Login({ onAuthenticated, onVisitor, onBack }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [wantStorm, setWantStorm] = useState(true)
  const [wantAgro, setWantAgro] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const googleButtonRef = useRef<HTMLDivElement>(null)

  function switchMode(next: 'login' | 'register') {
    setMode(next)
    setError(null)
    setPassword('')
    setConfirmPassword('')
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (mode === 'register' && password !== confirmPassword) {
      setError('As senhas não coincidem')
      return
    }
    if (mode === 'register' && password.length < MIN_PASSWORD_LENGTH) {
      setError(`A senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres`)
      return
    }
    if (mode === 'register' && !wantStorm && !wantAgro) {
      setError('Selecione pelo menos um módulo: Tempestade ou Agro')
      return
    }

    setLoading(true)
    try {
      if (mode === 'register') {
        await register(email, password, fullName.trim() || undefined, {
          storm: wantStorm,
          agro: wantAgro,
        })
      } else {
        await login(email, password)
      }
      onAuthenticated()
    } catch (err) {
      const fallback = mode === 'register' ? 'Falha ao criar conta' : 'Falha ao entrar'
      setError(err instanceof ApiError ? err.message : fallback)
    } finally {
      setLoading(false)
    }
  }

  // No VITE_GOOGLE_CLIENT_ID configured → the button just doesn't render.
  // Not an error state; most local/dev setups won't have one.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !googleButtonRef.current) return
    let cancelled = false
    loadGoogleScript()
      .then(() => {
        if (cancelled || !window.google || !googleButtonRef.current) return
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: async (response) => {
            setError(null)
            try {
              await loginWithGoogle(response.credential)
              onAuthenticated()
            } catch (err) {
              setError(err instanceof ApiError ? err.message : 'Falha ao entrar com Google')
            }
          },
        })
        window.google.accounts.id.renderButton(googleButtonRef.current, {
          theme: 'outline',
          size: 'large',
          width: 280,
        })
      })
      .catch(() => setError('Não foi possível carregar o login com Google'))
    return () => {
      cancelled = true
    }
  }, [onAuthenticated])

  const isRegister = mode === 'register'

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        {onBack && (
          <button type="button" className="link-btn back-link" onClick={onBack}>
            ← Voltar
          </button>
        )}
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        <p className="muted">
          {isRegister
            ? 'Criar conta — leva menos de um minuto.'
            : 'Painel administrativo — entre com sua conta.'}
        </p>

        {isRegister && (
          <>
            <label htmlFor="fullName">Nome (opcional)</label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              autoComplete="name"
              onChange={(e) => setFullName(e.target.value)}
              maxLength={120}
            />
          </>
        )}

        <label htmlFor="email">E-mail</label>
        <input
          id="email"
          type="email"
          value={email}
          autoComplete="username"
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label htmlFor="password">Senha</label>
        <input
          id="password"
          type="password"
          value={password}
          autoComplete={isRegister ? 'new-password' : 'current-password'}
          onChange={(e) => setPassword(e.target.value)}
          minLength={isRegister ? MIN_PASSWORD_LENGTH : undefined}
          required
        />

        {isRegister && (
          <>
            <label htmlFor="confirmPassword">Confirmar senha</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              autoComplete="new-password"
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={MIN_PASSWORD_LENGTH}
              required
            />

            <label>Módulos</label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={wantStorm}
                onChange={(e) => setWantStorm(e.target.checked)}
              />
              ⛈️ Tempestade
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={wantAgro}
                onChange={(e) => setWantAgro(e.target.checked)}
              />
              🌾 Agro
            </label>
          </>
        )}

        <button className="btn" type="submit" disabled={loading}>
          {loading ? (isRegister ? 'Criando conta…' : 'Entrando…') : isRegister ? 'Criar conta' : 'Entrar'}
        </button>
        {error && <p className="error">⚠️ {error}</p>}

        <p className="muted center">
          {isRegister ? (
            <>
              Já tem conta?{' '}
              <button type="button" className="link-btn" onClick={() => switchMode('login')}>
                Entrar
              </button>
            </>
          ) : (
            <>
              Não tem conta?{' '}
              <button type="button" className="link-btn" onClick={() => switchMode('register')}>
                Criar conta
              </button>
            </>
          )}
        </p>

        {GOOGLE_CLIENT_ID && !isRegister && (
          <>
            <p className="muted center">ou</p>
            <div ref={googleButtonRef} className="google-btn" />
          </>
        )}

        <button type="button" className="btn ghost" onClick={onVisitor}>
          Ver sem login
        </button>
      </form>
    </div>
  )
}
