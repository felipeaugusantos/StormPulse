import { useEffect, useRef, useState } from 'react'
import { ApiError, login, loginWithGoogle } from '../api'

interface Props {
  onAuthenticated: () => void
  onVisitor: () => void
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID
const GOOGLE_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'

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

export function Login({ onAuthenticated, onVisitor }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const googleButtonRef = useRef<HTMLDivElement>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await login(email, password)
      onAuthenticated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao entrar')
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

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        <p className="muted">Painel administrativo — entre com sua conta.</p>

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
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        <button className="btn" type="submit" disabled={loading}>
          {loading ? 'Entrando…' : 'Entrar'}
        </button>
        {error && <p className="error">⚠️ {error}</p>}

        {GOOGLE_CLIENT_ID && (
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
