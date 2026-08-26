import { useState } from 'react'
import { ApiError, resetPassword } from '../api'

interface Props {
  token: string
  onDone: () => void
}

const MIN_PASSWORD_LENGTH = 8

/** Landing page for the link sent by /auth/forgot-password (FASE 8) —
 * reached via a plain page load, never requires an existing session
 * (the token itself proves the request). `onDone` sends the user on to
 * the login screen after a successful reset. */
export function ResetPassword({ token, onDone }: Props) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError('As senhas não coincidem')
      return
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`A senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres`)
      return
    }
    setLoading(true)
    try {
      await resetPassword(token, password)
      setDone(true)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? 'Este link de redefinição é inválido, expirou ou já foi usado. Peça um novo.'
          : 'Falha ao redefinir a senha',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        {done ? (
          <>
            <p className="muted">✅ Senha redefinida com sucesso!</p>
            <button className="btn" type="button" onClick={onDone}>
              Ir para o login
            </button>
          </>
        ) : (
          <form onSubmit={submit}>
            <p className="muted">Escolha uma nova senha.</p>
            <label htmlFor="newPassword">Nova senha</label>
            <input
              id="newPassword"
              type="password"
              value={password}
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
              minLength={MIN_PASSWORD_LENGTH}
              required
            />
            <label htmlFor="confirmNewPassword">Confirmar nova senha</label>
            <input
              id="confirmNewPassword"
              type="password"
              value={confirmPassword}
              autoComplete="new-password"
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={MIN_PASSWORD_LENGTH}
              required
            />
            <button className="btn" type="submit" disabled={loading}>
              {loading ? 'Salvando…' : 'Salvar nova senha'}
            </button>
            {error && <p className="error">⚠️ {error}</p>}
          </form>
        )}
      </div>
    </div>
  )
}
