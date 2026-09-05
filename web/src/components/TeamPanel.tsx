import { useEffect, useState } from 'react'
import { api } from '../api'
import type { LocationItem, Organization, OrganizationMember, OrganizationRole } from '../types'

const ROLES: OrganizationRole[] = ['admin', 'agronomist', 'operator', 'viewer']
const LABEL: Record<OrganizationRole, string> = { owner: 'Proprietário', admin: 'Administrador',
  agronomist: 'Agrônomo', operator: 'Operador', viewer: 'Visualizador' }

export function TeamPanel({ locations, onBack }: { locations: LocationItem[]; onBack: () => void }) {
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrganizationMember[]>([])
  const [email, setEmail] = useState(''); const [role, setRole] = useState<OrganizationRole>('viewer')
  const [locationId, setLocationId] = useState(''); const [temporaryUntil, setTemporaryUntil] = useState('')
  const [message, setMessage] = useState('')
  async function load() {
    const [org, list] = await Promise.all([api.organization(), api.organizationMembers()])
    setOrganization(org); setMembers(list)
  }
  useEffect(() => { load().catch(() => setMessage('Sem permissão para gerenciar a equipe.')) }, [])
  async function invite(event: React.FormEvent) {
    event.preventDefault(); setMessage('Enviando…')
    try {
      await api.inviteOrganizationMember({ email, role, location_id: locationId || null,
        access_expires_at: temporaryUntil ? new Date(temporaryUntil).toISOString() : null })
      setEmail(''); setMessage('Convite enviado por e-mail.')
    } catch { setMessage('Não foi possível enviar o convite.') }
  }
  async function revoke(member: OrganizationMember) {
    if (!window.confirm(`Revogar imediatamente o acesso de ${member.email}?`)) return
    await api.revokeOrganizationMember(member.id); await load()
  }
  return <main className="admin-page"><button className="btn ghost" onClick={onBack}>← Voltar</button>
    <h1>Equipe · {organization?.name ?? 'Organização'}</h1>
    <form className="team-invite" onSubmit={invite}>
      <input type="email" required placeholder="membro@empresa.com" value={email} onChange={(e) => setEmail(e.target.value)} />
      <select value={role} onChange={(e) => setRole(e.target.value as OrganizationRole)}>
        {ROLES.map((item) => <option key={item} value={item}>{LABEL[item]}</option>)}
      </select>
      <select value={locationId} onChange={(e) => setLocationId(e.target.value)}>
        <option value="">Toda a organização</option>
        {locations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      <label>Até <input type="datetime-local" value={temporaryUntil} onChange={(e) => setTemporaryUntil(e.target.value)} /></label>
      <button className="btn" type="submit">Convidar</button>
    </form>
    {message && <p>{message}</p>}
    <div className="team-list">{members.map((member) => <article key={member.id} className="panel">
      <strong>{member.full_name || member.email}</strong><span>{member.email}</span>
      <span>{LABEL[member.role]} · {member.organization_wide_access ? 'organização' : 'acesso restrito'}</span>
      {member.access_expires_at && <span>Expira em {new Date(member.access_expires_at).toLocaleString('pt-BR')}</span>}
      {member.role !== 'owner' && member.is_active && <button className="btn danger" onClick={() => revoke(member)}>Revogar</button>}
    </article>)}</div>
  </main>
}
