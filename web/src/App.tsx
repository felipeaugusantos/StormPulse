import { useEffect, useState } from 'react'
import { initSession, logout } from './api'
import { Login } from './components/Login'
import { Dashboard } from './components/Dashboard'
import { LandingPage } from './components/LandingPage'
import { VisitorView } from './components/VisitorView'
import { VerifyEmail } from './components/VerifyEmail'
import { ResetPassword } from './components/ResetPassword'

type View = 'checking' | 'landing' | 'login' | 'visitor' | 'authed'

// E-mail links (verify-email/reset-password, FASE 8) land here via a plain
// page load, not SPA navigation — nginx's try_files falls back to
// index.html for any path (web/nginx.conf), so this just has to read the
// URL once on boot before the normal checking/landing/login flow below
// ever runs. Neither of these needs an existing session.
function readDeepLink(): { kind: 'verify-email' | 'reset-password'; token: string } | null {
  const { pathname, search } = window.location
  const token = new URLSearchParams(search).get('token')
  if (!token) return null
  if (pathname === '/verificar-email') return { kind: 'verify-email', token }
  if (pathname === '/redefinir-senha') return { kind: 'reset-password', token }
  return null
}

export default function App() {
  const [view, setView] = useState<View>('checking')
  const [deepLink] = useState(readDeepLink)

  // Hardening Fase 4 (ADR-0045): no synchronous localStorage check
  // anymore — the only thing that can prove a session is still valid is
  // asking the backend to redeem the HttpOnly refresh cookie for a fresh
  // access token. Shows nothing conclusive until that resolves either way.
  useEffect(() => {
    if (deepLink) return
    let cancelled = false
    initSession().then((ok) => {
      if (!cancelled) setView(ok ? 'authed' : 'landing')
    })
    return () => {
      cancelled = true
    }
  }, [deepLink])

  function backToLogin() {
    window.history.replaceState(null, '', '/')
    setView('login')
  }

  if (deepLink?.kind === 'verify-email') {
    return <VerifyEmail token={deepLink.token} onDone={backToLogin} />
  }
  if (deepLink?.kind === 'reset-password') {
    return <ResetPassword token={deepLink.token} onDone={backToLogin} />
  }

  async function handleLogout() {
    await logout()
    setView('login')
  }

  if (view === 'checking') {
    return (
      <div className="login-wrap">
        <p className="muted">Carregando…</p>
      </div>
    )
  }
  if (view === 'authed') {
    return <Dashboard onLogout={handleLogout} />
  }
  if (view === 'visitor') {
    return <VisitorView onBack={() => setView('landing')} />
  }
  if (view === 'landing') {
    return <LandingPage onEnter={() => setView('login')} onVisitor={() => setView('visitor')} />
  }
  return (
    <Login
      onAuthenticated={() => setView('authed')}
      onVisitor={() => setView('visitor')}
      onBack={() => setView('landing')}
    />
  )
}
