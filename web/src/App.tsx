import { useEffect, useState } from 'react'
import { initSession, logout } from './api'
import { Login } from './components/Login'
import { Dashboard } from './components/Dashboard'
import { VisitorView } from './components/VisitorView'

type View = 'checking' | 'login' | 'visitor' | 'authed'

export default function App() {
  const [view, setView] = useState<View>('checking')

  // Hardening Fase 4 (ADR-0045): no synchronous localStorage check
  // anymore — the only thing that can prove a session is still valid is
  // asking the backend to redeem the HttpOnly refresh cookie for a fresh
  // access token. Shows nothing conclusive until that resolves either way.
  useEffect(() => {
    let cancelled = false
    initSession().then((ok) => {
      if (!cancelled) setView(ok ? 'authed' : 'login')
    })
    return () => {
      cancelled = true
    }
  }, [])

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
    return <VisitorView onBack={() => setView('login')} />
  }
  return (
    <Login onAuthenticated={() => setView('authed')} onVisitor={() => setView('visitor')} />
  )
}
