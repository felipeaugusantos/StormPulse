import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import { formatDateTimeBR } from '../format'
import type { ApiKey, ApiKeyCreated } from '../types'

interface Props {
  onClose: () => void
}

/** Gestão de chaves de API pra integração externa (item 1, ADR-0062). O
 * valor bruto de uma chave só aparece uma vez, na criação — depois disso
 * o backend só guarda o hash, então esta tela nunca mais consegue mostrar
 * de novo. */
export function ApiKeysModal({ onClose }: Props) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null)
  const [newName, setNewName] = useState('')
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  async function reload() {
    try {
      setKeys(await api.listApiKeys())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao carregar chaves')
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    setCreating(true)
    setError(null)
    try {
      const created = await api.createApiKey(newName.trim())
      setJustCreated(created)
      setNewName('')
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao criar chave')
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke(keyId: string) {
    if (!window.confirm('Revogar esta chave? Qualquer integração usando ela para de funcionar.')) {
      return
    }
    try {
      await api.revokeApiKey(keyId)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao revogar chave')
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🔑 Chaves de API</h2>
          <button type="button" className="link-btn" onClick={onClose} aria-label="Fechar">
            ✕
          </button>
        </div>
        <p className="muted">
          Pra integrar seus próprios sistemas aos dados de locais/risco/alertas da sua conta.
          Envie a chave no header <code>X-API-Key</code>.
        </p>

        {justCreated && (
          <div className="risk-badge risk-yellow">
            <p className="risk-badge-summary">
              ✅ Chave "{justCreated.name}" criada — copie agora, ela não aparece de novo:
            </p>
            <code style={{ display: 'block', wordBreak: 'break-all', margin: '6px 0' }}>
              {justCreated.key}
            </code>
            <button type="button" className="link-btn" onClick={() => setJustCreated(null)}>
              Ok, já copiei
            </button>
          </div>
        )}

        <form onSubmit={handleCreate} className="checkbox-row" style={{ gap: 8 }}>
          <input
            type="text"
            placeholder="Nome da chave (ex: integração ERP)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={120}
            style={{ flex: 1 }}
          />
          <button className="btn" type="submit" disabled={creating || !newName.trim()}>
            {creating ? 'Criando…' : 'Criar'}
          </button>
        </form>
        {error && <p className="error">⚠️ {error}</p>}

        {keys === null ? (
          <p className="panel-hint">carregando…</p>
        ) : keys.length === 0 ? (
          <p className="empty">Nenhuma chave criada ainda.</p>
        ) : (
          <div className="list">
            {keys.map((k) => (
              <div className="row" key={k.id}>
                <span className={`badge ${k.revoked_at ? 'red' : 'green'}`}>
                  {k.revoked_at ? 'revogada' : 'ativa'}
                </span>
                <div className="grow">
                  <div>
                    {k.name} <code>{k.key_prefix}…</code>
                  </div>
                  <div className="sub muted">
                    criada em {formatDateTimeBR(k.created_at)} · último uso:{' '}
                    {k.last_used_at ? formatDateTimeBR(k.last_used_at) : 'nunca'}
                  </div>
                </div>
                {!k.revoked_at && (
                  <button type="button" className="link-btn" onClick={() => handleRevoke(k.id)}>
                    Revogar
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
