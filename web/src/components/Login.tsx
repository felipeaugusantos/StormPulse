import { useEffect, useRef, useState } from 'react'
import { ApiError, forgotPassword, login, loginWithGoogle, register } from '../api'
import { TermsModal } from './TermsModal'

interface Props {
  onAuthenticated: () => void
  onVisitor: () => void
  onBack?: () => void
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID
const GOOGLE_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
const HCAPTCHA_SITE_KEY = import.meta.env.VITE_HCAPTCHA_SITE_KEY
const HCAPTCHA_SCRIPT_SRC = 'https://js.hcaptcha.com/1/api.js?render=explicit'
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

function loadHcaptchaScript(): Promise<void> {
  if (window.hcaptcha) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${HCAPTCHA_SCRIPT_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve())
      return
    }
    const script = document.createElement('script')
    script.src = HCAPTCHA_SCRIPT_SRC
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Falha ao carregar o hCaptcha'))
    document.head.appendChild(script)
  })
}

type Mode = 'login' | 'register' | 'forgot'

export function Login({ onAuthenticated, onVisitor, onBack }: Props) {
  const [mode, setMode] = useState<Mode>('login')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [wantStorm, setWantStorm] = useState(true)
  const [wantAgro, setWantAgro] = useState(false)
  const [acceptTerms, setAcceptTerms] = useState(false)
  const [showTerms, setShowTerms] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const googleButtonRef = useRef<HTMLDivElement>(null)
  const captchaRef = useRef<HTMLDivElement>(null)
  const captchaWidgetId = useRef<string | null>(null)
  const captchaToken = useRef<string>('')

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setInfo(null)
    setPassword('')
    setConfirmPassword('')
    setForgotSent(false)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setInfo(null)

    if (mode === 'forgot') {
      setLoading(true)
      try {
        await forgotPassword(email)
      } catch {
        // Ignored on purpose: the backend always responds 204 whether or
        // not the e-mail exists, so any error here is a real network/
        // server problem, not "e-mail não encontrado" — the message below
        // stays the same either way, never revealing which case happened.
      } finally {
        setLoading(false)
        setForgotSent(true)
      }
      return
    }

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
    if (mode === 'register' && !acceptTerms) {
      setError('É preciso aceitar os Termos de Uso e a Política de Privacidade')
      return
    }
    if (HCAPTCHA_SITE_KEY && !captchaToken.current) {
      setError('Confirme que você não é um robô')
      return
    }

    setLoading(true)
    try {
      if (mode === 'register') {
        const autoLoggedIn = await register(
          email,
          password,
          fullName.trim() || undefined,
          { storm: wantStorm, agro: wantAgro },
          acceptTerms,
          captchaToken.current || undefined,
        )
        if (autoLoggedIn) {
          onAuthenticated()
        } else {
          // The account was created — only the auto-login right after it
          // couldn't reuse the same (single-use) captcha token. Not an
          // error: send them to the login form instead of a scary message.
          switchMode('login')
          setInfo('Conta criada! Entre com seu e-mail e senha.')
        }
      } else {
        await login(email, password, captchaToken.current || undefined)
        onAuthenticated()
      }
    } catch (err) {
      const fallback = mode === 'register' ? 'Falha ao criar conta' : 'Falha ao entrar'
      setError(err instanceof ApiError ? err.message : fallback)
    } finally {
      setLoading(false)
      if (window.hcaptcha && captchaWidgetId.current) {
        window.hcaptcha.reset(captchaWidgetId.current)
        captchaToken.current = ''
      }
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

  // No VITE_HCAPTCHA_SITE_KEY configured → the widget just doesn't render,
  // and captcha_token is never required (matches the backend, which only
  // requires it when HCAPTCHA_SECRET_KEY is set). Re-rendered for both
  // login and register modes (the "forgot" mode never shows it).
  useEffect(() => {
    if (!HCAPTCHA_SITE_KEY || !captchaRef.current || mode === 'forgot') return
    let cancelled = false
    loadHcaptchaScript()
      .then(() => {
        if (cancelled || !window.hcaptcha || !captchaRef.current) return
        captchaWidgetId.current = window.hcaptcha.render(captchaRef.current, {
          sitekey: HCAPTCHA_SITE_KEY,
          callback: (token) => {
            captchaToken.current = token
          },
        })
      })
      .catch(() => setError('Não foi possível carregar a verificação anti-abuso'))
    return () => {
      cancelled = true
    }
  }, [mode])

  const isRegister = mode === 'register'
  const isForgot = mode === 'forgot'

  return (
    <div className="login-wrap">
      {showTerms && <TermsModal onClose={() => setShowTerms(false)} />}
      <form className="login-card" onSubmit={submit}>
        {onBack && (
          <button type="button" className="link-btn back-link" onClick={onBack}>
            ← Voltar
          </button>
        )}
        {onBack ? (
          <button
            type="button"
            className="brand brand-link"
            onClick={onBack}
            title="Voltar para a página inicial"
          >
            <span aria-hidden>⚡</span>
            <span>
              Storm<strong>Pulse</strong>
            </span>
          </button>
        ) : (
          <div className="brand">
            <span aria-hidden>⚡</span>
            <span>
              Storm<strong>Pulse</strong>
            </span>
          </div>
        )}
        <p className="muted">
          {isForgot
            ? 'Redefinir senha — informe seu e-mail.'
            : isRegister
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

        {isForgot && forgotSent ? (
          <p className="muted">
            Se esse e-mail estiver cadastrado, enviamos um link de redefinição de senha para
            ele. Confira sua caixa de entrada (e o spam).
          </p>
        ) : (
          <>
            {!isForgot && (
              <>
                <div className="label-row">
                  <label htmlFor="password">Senha</label>
                  {!isRegister && (
                    <button
                      type="button"
                      className="link-btn small"
                      onClick={() => switchMode('forgot')}
                    >
                      Esqueci minha senha?
                    </button>
                  )}
                </div>
                <input
                  id="password"
                  type="password"
                  value={password}
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={isRegister ? MIN_PASSWORD_LENGTH : undefined}
                  required
                />
              </>
            )}

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

                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={acceptTerms}
                    onChange={(e) => setAcceptTerms(e.target.checked)}
                    required
                  />
                  Li e aceito os{' '}
                  <button type="button" className="link-btn" onClick={() => setShowTerms(true)}>
                    Termos de Uso e a Política de Privacidade
                  </button>
                </label>
              </>
            )}

            {HCAPTCHA_SITE_KEY && !isForgot && <div ref={captchaRef} style={{ margin: '4px 0' }} />}

            <button className="btn" type="submit" disabled={loading}>
              {isForgot
                ? loading
                  ? 'Enviando…'
                  : 'Enviar link de redefinição'
                : loading
                  ? isRegister
                    ? 'Criando conta…'
                    : 'Entrando…'
                  : isRegister
                    ? 'Criar conta'
                    : 'Entrar'}
            </button>
          </>
        )}

        {error && <p className="error">⚠️ {error}</p>}
        {info && <p className="muted">✅ {info}</p>}

        <p className="muted center">
          {isForgot ? (
            <button type="button" className="link-btn" onClick={() => switchMode('login')}>
              Voltar para entrar
            </button>
          ) : isRegister ? (
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

        {GOOGLE_CLIENT_ID && !isRegister && !isForgot && (
          <>
            <p className="muted center">ou</p>
            <div ref={googleButtonRef} className="google-btn" />
          </>
        )}

        {!isForgot && (
          <button type="button" className="btn ghost" onClick={onVisitor}>
            Ver sem login
          </button>
        )}
      </form>
    </div>
  )
}
