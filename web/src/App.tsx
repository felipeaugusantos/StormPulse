import { useState } from 'react'
import { clearToken, getToken } from './api'
import { Login } from './components/Login'
import { Dashboard } from './components/Dashboard'

export default function App() {
  const [authed, setAuthed] = useState<boolean>(() => getToken() !== null)

  function handleLogout() {
    clearToken()
    setAuthed(false)
  }

  if (!authed) {
    return <Login onAuthenticated={() => setAuthed(true)} />
  }
  return <Dashboard onLogout={handleLogout} />
}
