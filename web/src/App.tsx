import { useState } from 'react'
import { clearToken, getToken } from './api'
import { Login } from './components/Login'
import { Dashboard } from './components/Dashboard'
import { VisitorView } from './components/VisitorView'

type View = 'login' | 'visitor' | 'authed'

export default function App() {
  const [view, setView] = useState<View>(() => (getToken() !== null ? 'authed' : 'login'))

  function handleLogout() {
    clearToken()
    setView('login')
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
