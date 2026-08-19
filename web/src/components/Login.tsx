import { useState } from 'react'
import { ApiError, login, setToken } from '../api'

interface Props {
  onAuthenticated: () => void
}

export function Login({ onAuthenticated }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const token = await login(email, password)
      setToken(token)
      onAuthenticated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao entrar')
    } finally {
      setLoading(false)
    }
  }

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
      </form>
    </div>
  )
}
