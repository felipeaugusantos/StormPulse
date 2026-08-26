import { useEffect, useState } from 'react'
import { ApiError, verifyEmail } from '../api'

interface Props {
  token: string
  onDone: () => void
}

/** Landing page for the link sent by /auth/verify-email (FASE 8) — reached
 * via a plain page load (e-mail links aren't SPA navigation), so this runs
 * once on mount and reports the result; `onDone` sends the user on to the
 * login screen either way. */
export function VerifyEmail({ token, onDone }: Props) {
  const [status, setStatus] = useState<'checking' | 'ok' | 'error'>('checking')

  useEffect(() => {
    let cancelled = false
    verifyEmail(token)
      .then(() => {
        if (!cancelled) setStatus('ok')
      })
      .catch((err) => {
        if (cancelled) return
        setStatus('error')
        if (!(err instanceof ApiError)) throw err
      })
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        {status === 'checking' && <p className="muted">Confirmando seu e-mail…</p>}
        {status === 'ok' && <p className="muted">✅ E-mail confirmado com sucesso!</p>}
        {status === 'error' && (
          <p className="error">
            ⚠️ Este link de confirmação é inválido ou já expirou. Você pode pedir um novo depois
            de entrar na sua conta.
          </p>
        )}
        <button className="btn" type="button" onClick={onDone}>
          Ir para o login
        </button>
      </div>
    </div>
  )
}
