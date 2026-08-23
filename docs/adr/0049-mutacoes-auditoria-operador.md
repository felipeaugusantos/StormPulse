# ADR-0049 — Painel de operador: mutações e auditoria (Fase 2)

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

O ADR-0048 entregou só leitura (listar tenants/usuários cross-tenant).
Esta fase adiciona o que ficou explicitamente fora de escopo lá:
ativar/desativar conta e trocar o role tenant-scoped de um usuário —
com log de auditoria desde o primeiro commit, não como retrofit
(decisão já registrada no ADR-0048).

## Decisão

**Nova tabela `admin_audit_log`** — global, sem `TenantMixin` (uma ação
de operador pode atravessar qualquer tenant). Cada linha grava
`actor_user_id`/`actor_email`, `action`, `target_user_id`/`target_email`
e um `detail` (JSONB) com o diff exato (`{"is_active": {"from": true,
"to": false}}`). E-mails do ator e do alvo são denormalizados
(`ondelete="SET NULL"` nas FKs) — o registro do que aconteceu precisa
sobreviver mesmo que a conta envolvida seja apagada depois.

**`PUT /api/v1/admin/users/{user_id}`** — corpo `{is_active?, role?,
confirm}`. `confirm` é obrigatório (sem valor default, mesmo padrão de
`DeleteAccountIn`) — omiti-lo é erro de validação (422) antes mesmo de
chegar no handler; enviá-lo como `false` chega no handler e é rejeitado
explicitamente (400). Cada campo que de fato muda de valor grava sua
própria linha de auditoria — reenviar um valor já vigente não gera
ruído no log.

**Guarda-corpos**:
- `role` só aceita `user`/`admin` — as roles reservadas
  (`meteorologist`/`company_admin`/`operator`) não têm nenhuma
  implementação real ainda; conceder uma delas seria uma mudança de
  permissão que nada no app entende, um no-op disfarçado de ação real.
- Um operador **não pode desativar a própria conta** — proteção contra
  lockout acidental. Nada impede um operador de desativar *outro*
  operador, ou de trocar o próprio role tenant-scoped (isso não afeta
  `is_platform_admin`, que continua fora do escopo de mutação desta
  fase — só o bootstrap por variável de ambiente mexe nele).
- Usuário alvo inexistente → 404.

**`GET /api/v1/admin/audit-log`** — paginado, mais recente primeiro.

**Frontend**: cada linha da aba "Usuários" ganhou um `<select>` de role
e um botão Ativar/Desativar, os dois com `window.confirm()` antes de
qualquer chamada (mesmo padrão já usado em "Excluir conta"). A própria
conta do operador aparece com o botão de desativar genuinamente
`disabled` (confirmado via DOM, não só escondido) e uma tag "VOCÊ". Aba
nova "Auditoria" lista o histórico.

## Verificação

- Backend: 9 testes de integração novos (403 pra não-operador nos dois
  endpoints novos; 422 com `confirm` ausente; 400 com `confirm: false`;
  desativar gera exatamente a entrada de auditoria esperada e a conta
  não consegue mais logar depois; troca de role idem; role não
  suportado rejeitado; auto-desativação bloqueada; usuário inexistente
  404; nenhum campo informado 400). Suíte completa (91% cobertura),
  ruff e mypy verdes.
- Web: `tsc -b`, suíte de testes e `npm run build` verdes.
- Verificado em navegador real contra a stack local + `curl` direto:
  desativar `cliente@example.com` de fato impede login subsequente
  (`401 Credenciais inválidas`); a entrada certa aparece em
  `/admin/audit-log` com `actor_email`/`target_email`/`detail`
  corretos; reativar reverte; o botão "Desativar" da própria conta do
  operador está genuinamente `disabled` no DOM, não só sem estilo.

## Consequências

- Pela primeira vez existe uma trilha auditável de quem alterou o quê
  no sistema — condição necessária pra qualquer discussão futura de
  compliance/LGPD sobre acesso administrativo a dados de clientes.
- Ainda fora de escopo: conceder/revogar `is_platform_admin` por essa
  UI (continua só via `PLATFORM_ADMIN_EMAIL` + restart), e revogação
  forçada de sessão (depende da tabela de sessões já registrada como
  risco residual no ADR-0045).
