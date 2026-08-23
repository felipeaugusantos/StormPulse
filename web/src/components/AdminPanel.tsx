import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { AdminTenant, AdminUser } from '../types'

interface Props {
  onBack: () => void
}

const PAGE_SIZE = 100

export function AdminPanel({ onBack }: Props) {
  const [tab, setTab] = useState<'users' | 'tenants'>('users')
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [tenantsTotal, setTenantsTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (tab === 'users') {
        const res = await api.adminUsers({ search: searchQuery || undefined, limit: PAGE_SIZE })
        setUsers(res.items)
        setUsersTotal(res.total)
      } else {
        const res = await api.adminTenants({ search: searchQuery || undefined, limit: PAGE_SIZE })
        setTenants(res.items)
        setTenantsTotal(res.total)
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

  function switchTab(next: 'users' | 'tenants') {
    setTab(next)
    setSearchInput('')
    setSearchQuery('')
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
          </div>

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

          {tab === 'users' ? (
            <>
              <h2>
                Usuários <span className="count">{usersTotal}</span>
              </h2>
              <div className="list">
                {!loading && users.length === 0 && <p className="empty">Nenhum usuário encontrado.</p>}
                {users.map((u) => (
                  <div className="row" key={u.id}>
                    <span className={`badge ${u.is_active ? 'green' : 'red'}`}>
                      {u.is_active ? 'ativo' : 'inativo'}
                    </span>
                    <div className="grow">
                      <div>
                        {u.email}
                        {u.is_platform_admin && <span className="mock-tag">OPERADOR</span>}
                      </div>
                      <div className="sub">
                        {u.full_name || 'sem nome'} · {u.tenant_name} · {u.role}
                      </div>
                      <div className="sub muted">
                        criado em {new Date(u.created_at).toLocaleDateString('pt-BR')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
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
        </section>
      </div>
    </>
  )
}
