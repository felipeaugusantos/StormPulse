import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { AdminAuditLogEntry, AdminStats, AdminTenant, AdminUser } from '../types'

interface Props {
  onBack: () => void
  meId: string | null
}

const PAGE_SIZE = 100
const ROLE_OPTIONS = ['user', 'admin']

export function AdminPanel({ onBack, meId }: Props) {
  const [tab, setTab] = useState<'stats' | 'users' | 'tenants' | 'audit'>('stats')
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [tenantsTotal, setTenantsTotal] = useState(0)
  const [auditLog, setAuditLog] = useState<AdminAuditLogEntry[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mutatingId, setMutatingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (tab === 'stats') {
        setStats(await api.adminStats())
      } else if (tab === 'users') {
        const res = await api.adminUsers({ search: searchQuery || undefined, limit: PAGE_SIZE })
        setUsers(res.items)
        setUsersTotal(res.total)
      } else if (tab === 'tenants') {
        const res = await api.adminTenants({ search: searchQuery || undefined, limit: PAGE_SIZE })
        setTenants(res.items)
        setTenantsTotal(res.total)
      } else {
        const res = await api.adminAuditLog({ limit: PAGE_SIZE })
        setAuditLog(res.items)
        setAuditTotal(res.total)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erro ao carregar')
    } finally {
      setLoading(false)
    }
  }, [tab, searchQuery])

  useEffect(() => {
    load()
  }, [load])

  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    setSearchQuery(searchInput.trim())
  }

  function switchTab(next: 'stats' | 'users' | 'tenants' | 'audit') {
    setTab(next)
    setSearchInput('')
    setSearchQuery('')
  }

  async function toggleActive(u: AdminUser) {
    const verb = u.is_active ? 'desativar' : 'ativar'
    if (!window.confirm(`Tem certeza que quer ${verb} a conta ${u.email}?`)) return
    setMutatingId(u.id)
    setError(null)
    try {
      await api.adminUpdateUser(u.id, { is_active: !u.is_active })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Erro ao ${verb} conta`)
    } finally {
      setMutatingId(null)
    }
  }

  async function changeRole(u: AdminUser, nextRole: string) {
    if (nextRole === u.role) return
    if (
      !window.confirm(`Tem certeza que quer mudar o role de ${u.email} de "${u.role}" para "${nextRole}"?`)
    ) {
      return
    }
    setMutatingId(u.id)
    setError(null)
    try {
      await api.adminUpdateUser(u.id, { role: nextRole })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erro ao mudar role')
    } finally {
      setMutatingId(null)
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span aria-hidden>🛠️</span>
          <span>
            Storm<strong>Pulse</strong> Admin — Operador
          </span>
        </div>
        <div className="spacer" />
        <button className="btn ghost" onClick={onBack}>
          ← Voltar ao painel
        </button>
      </header>

      <div className="dashboard-body">
        {error && <div className="panel error">⚠️ {error}</div>}

        <section className="panel">
          <div className="admin-tabs">
            <button
              type="button"
              className={`btn small ${tab === 'stats' ? '' : 'ghost'}`}
              onClick={() => switchTab('stats')}
            >
              Métricas
            </button>
            <button
              type="button"
              className={`btn small ${tab === 'users' ? '' : 'ghost'}`}
              onClick={() => switchTab('users')}
            >
              Usuários
            </button>
            <button
              type="button"
              className={`btn small ${tab === 'tenants' ? '' : 'ghost'}`}
              onClick={() => switchTab('tenants')}
            >
              Tenants
            </button>
            <button
              type="button"
              className={`btn small ${tab === 'audit' ? '' : 'ghost'}`}
              onClick={() => switchTab('audit')}
            >
              Auditoria
            </button>
          </div>

          {tab !== 'audit' && tab !== 'stats' && (
            <form className="location-search-row" onSubmit={submitSearch}>
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={tab === 'users' ? 'Buscar por e-mail' : 'Buscar por nome do tenant'}
              />
              <button className="btn small" type="submit" disabled={loading}>
                Buscar
              </button>
            </form>
          )}

          {tab === 'stats' && (
            <>
              <h2>Métricas</h2>
              {!stats && !loading && <p className="empty">Não foi possível carregar as métricas.</p>}
              {stats && (
                <div className="admin-stats-grid">
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.total_tenants}</div>
                    <div className="admin-stat-label">Tenants</div>
                  </div>
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.total_users}</div>
                    <div className="admin-stat-label">Usuários</div>
                  </div>
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.active_users_7d}</div>
                    <div className="admin-stat-label">Ativos (7 dias)</div>
                  </div>
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.active_users_30d}</div>
                    <div className="admin-stat-label">Ativos (30 dias)</div>
                  </div>
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.total_locations}</div>
                    <div className="admin-stat-label">Locais monitorados</div>
                  </div>
                  <div className="admin-stat-card">
                    <div className="admin-stat-value">{stats.alerts_last_30d}</div>
                    <div className="admin-stat-label">Alertas (30 dias)</div>
                  </div>
                </div>
              )}
            </>
          )}

          {tab === 'users' && (
            <>
              <h2>
                Usuários <span className="count">{usersTotal}</span>
              </h2>
              <div className="list">
                {!loading && users.length === 0 && <p className="empty">Nenhum usuário encontrado.</p>}
                {users.map((u) => {
                  const isSelf = u.id === meId
                  const busy = mutatingId === u.id
                  return (
                    <div className="row" key={u.id}>
                      <span className={`badge ${u.is_active ? 'green' : 'red'}`}>
                        {u.is_active ? 'ativo' : 'inativo'}
                      </span>
                      <div className="grow">
                        <div>
                          {u.email}
                          {u.is_platform_admin && <span className="mock-tag">OPERADOR</span>}
                          {isSelf && <span className="mock-tag">VOCÊ</span>}
                        </div>
                        <div className="sub">
                          {u.full_name || 'sem nome'} · {u.tenant_name}
                        </div>
                        <div className="sub muted">
                          criado em {new Date(u.created_at).toLocaleDateString('pt-BR')} · último
                          login:{' '}
                          {u.last_login_at
                            ? new Date(u.last_login_at).toLocaleString('pt-BR')
                            : 'nunca'}
                        </div>
                      </div>
                      <select
                        className="admin-role-select"
                        value={u.role}
                        disabled={busy || !ROLE_OPTIONS.includes(u.role)}
                        onChange={(e) => changeRole(u, e.target.value)}
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                        {!ROLE_OPTIONS.includes(u.role) && <option value={u.role}>{u.role}</option>}
                      </select>
                      <button
                        type="button"
                        className="btn ghost small"
                        disabled={busy || isSelf}
                        title={isSelf ? 'Você não pode desativar sua própria conta' : undefined}
                        onClick={() => toggleActive(u)}
                      >
                        {u.is_active ? 'Desativar' : 'Ativar'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {tab === 'tenants' && (
            <>
              <h2>
                Tenants <span className="count">{tenantsTotal}</span>
              </h2>
              <div className="list">
                {!loading && tenants.length === 0 && <p className="empty">Nenhum tenant encontrado.</p>}
                {tenants.map((t) => (
                  <div className="row" key={t.id}>
                    <span className={`badge ${t.is_active ? 'green' : 'red'}`}>
                      {t.is_active ? 'ativo' : 'inativo'}
                    </span>
                    <div className="grow">
                      <div>{t.name}</div>
                      <div className="sub">
                        {t.user_count} usuário{t.user_count === 1 ? '' : 's'} · {t.location_count}{' '}
                        {t.location_count === 1 ? 'local monitorado' : 'locais monitorados'}
                      </div>
                      <div className="sub muted">
                        criado em {new Date(t.created_at).toLocaleDateString('pt-BR')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === 'audit' && (
            <>
              <h2>
                Auditoria <span className="count">{auditTotal}</span>
              </h2>
              <div className="list">
                {!loading && auditLog.length === 0 && (
                  <p className="empty">Nenhuma ação administrativa registrada ainda.</p>
                )}
                {auditLog.map((entry) => (
                  <div className="row" key={entry.id}>
                    <span className="badge sev">{entry.action}</span>
                    <div className="grow">
                      <div>
                        {entry.actor_email} → {entry.target_email || '—'}
                      </div>
                      <div className="sub">{JSON.stringify(entry.detail)}</div>
                      <div className="sub muted">
                        {new Date(entry.created_at).toLocaleString('pt-BR')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  )
}
