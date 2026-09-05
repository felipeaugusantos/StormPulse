import { useState } from 'react'
import { api } from '../api'

export function AcceptInvitation({ token, onDone }: { token: string; onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [status, setStatus] = useState<'idle' | 'busy' | 'done' | 'error'>('idle')
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setStatus('busy')
    try {
      await api.acceptOrganizationInvitation({ token, password, full_name: name || undefined })
      setStatus('done')
    } catch { setStatus('error') }
  }
  return <div className="login-wrap"><form className="login-card" onSubmit={submit}>
    <h1>Aceitar convite</h1>
    {status === 'done' ? <><p>Acesso criado. Entre com o e-mail que recebeu o convite.</p>
      <button type="button" onClick={onDone}>Ir para o login</button></> : <>
      <label>Nome<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Senha<input type="password" minLength={8} required value={password}
        onChange={(e) => setPassword(e.target.value)} /></label>
      {status === 'error' && <p className="error">Convite expirado, revogado ou já utilizado.</p>}
      <button disabled={status === 'busy'}>{status === 'busy' ? 'Criando acesso…' : 'Aceitar convite'}</button>
    </>}
  </form></div>
}
