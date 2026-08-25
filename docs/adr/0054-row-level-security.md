# ADR-0054 — Row-Level Security (isolação de tenant no próprio Postgres)

- **Status:** Aceito
- **Data:** 2026-08-25

## Contexto

Isolação por tenant sempre foi só em nível de aplicação — toda query já
filtra por `tenant_id` corretamente (auditado ao longo do projeto), mas
sem uma segunda trava caso uma query *futura* esqueça o filtro. RLS
(Row-Level Security) do Postgres faz essa falta ser **fail-closed** (zero
linhas) em vez de vazar dado entre tenants.

## Decisão

Habilitar RLS (`ENABLE` + `FORCE ROW LEVEL SECURITY`, com uma política
`tenant_isolation` por tabela) nas 9 tabelas com `tenant_id`: `users`,
`locations`, `alerts`, `alert_verifications`, `ndvi_readings`,
`notifications`, `push_subscriptions`, `user_reports`, `storm_risks`.

### Achado real que mudou o design inteiro

A abordagem óbvia — só adicionar as políticas, manter o único usuário
`stormpulse` de sempre — foi testada ao vivo contra um Postgres real
**antes** de escrever qualquer código de produção, e não funciona: o
usuário de bootstrap do Docker (`POSTGRES_USER`) é criado como
**superusuário**, e superusuário do Postgres **sempre ignora RLS**,
mesmo com `FORCE`. O Postgres também recusa remover o próprio
superusuário do usuário de bootstrap (`ALTER ROLE ... NOSUPERUSER`
falha: "The bootstrap user must have the SUPERUSER attribute").

Fix: a migração cria uma **segunda role, sem superusuário**,
`stormpulse_app`, com só DML nas tabelas — é essa role que a API e os
workers passam a usar em runtime (`app/core/config.py`:
`database_url`/`sync_database_url` agora usam `postgres_app_user`/
`postgres_app_password`; `migration_database_url`, usada só pelo Alembic,
continua com o superusuário — só ele pode `CREATE ROLE`/`GRANT`).

### Segundo achado real: `current_setting` não some, vira `''`

Depois de corrigir o superusuário, testes contra Postgres real (conexão
pooled, reaproveitada) revelaram um segundo problema: uma vez que um GUC
customizado (`app.tenant_id`) é setado via `SET LOCAL` em **qualquer**
transação anterior na mesma conexão, `current_setting('app.tenant_id',
true)` para de retornar `NULL` e passa a retornar **string vazia** (`''`)
nas transações seguintes daquela conexão — mesmo depois do `SET LOCAL`
reverter. `''::uuid` sempre lança erro (não é `NULL::uuid`), então toda
policy quebrava com "invalid input syntax for type uuid" no primeiro
request que reaproveitasse uma conexão do pool. Fix: `NULLIF(...,
'')::uuid` em vez de `...::uuid` direto — padrão conhecido pra esse
comportamento específico do Postgres.

### Terceiro achado real: `SET LOCAL` não sobrevive a um `commit()`

`SET LOCAL`/`set_config(..., true)` valem só até o fim da transação —
um `session.commit()` no meio de uma função que continua usando a mesma
sessão depois (`session.refresh()`, uma nova query) perde o GUC
silenciosamente (zero linhas, sem erro). Isso quebrou de verdade
`_create_tenant_and_user` (registro), o vínculo de conta Google,
`create_location`/`update_location`, `admin.update_user` e — o mais sério
— `run_ingestion_cycle` (o pruning de células mock comita antes do loop
de risco, que silenciosamente processava zero locations). Todos corrigidos
reaplicando o GUC (`app/core/rls.py`: `set_tenant_context`/`bypass_rls`,
versão síncrona em `workers/db.py`) logo após cada commit intermediário.

## Três pontos legítimos de acesso cross-tenant

1. `get_current_user`/`/auth/refresh` — o primeiro lookup de cada
   request é por `id` vindo de um JWT já assinado pelo próprio servidor,
   antes do tenant ser conhecido (é o que essa query descobre). Bypass
   só nesse lookup, substituído pelo tenant real logo em seguida.
2. `require_platform_admin` — depois do check `is_platform_admin` (na
   própria linha do usuário, já dentro do tenant dele), bypass fica
   ligado pelo resto do request — visão cross-tenant é o propósito do
   painel admin (FASE 28, ADR-0048).
3. `workers/db.py`'s `session_scope()` — todo ciclo de worker processa
   todos os tenants por design, nunca dirigido por input de usuário.

Todos os três usam o mesmo GUC explícito e auditável, `app.bypass_rls =
'on'` — nunca um `BYPASSRLS` de role, que derrubaria RLS silenciosamente
pra qualquer query naquela conexão, incluindo uma que ninguém revisou.

## Verificação

Toda a suíte de testes do backend (~300 testes, incluindo os de
integração contra Postgres real) passou depois das correções — rodada
localmente contra um Postgres real subido via `docker compose up -d db
redis` (não só CI), exatamente pra pegar os três achados acima antes de
qualquer deploy. `ruff`, `mypy --strict` e `pip-audit` verdes.

## Consequências

- `POSTGRES_APP_PASSWORD` precisa de um valor forte em produção — o
  padrão de desenvolvimento é recusado no startup quando
  `ENVIRONMENT=production` (mesmo padrão do `JWT_SECRET_KEY`).
- Qualquer novo caminho de escrita que comite no meio de uma função e
  continua lendo/escrevendo na mesma sessão precisa reaplicar o GUC —
  documentado em `app/core/rls.py`.
- Tabelas globais (`storm_cells`, `convective_watches`,
  `satellite_images`, `lightning_strikes`, `weather_sources`,
  `radar_frames`, `admin_audit_log`) ficam de fora de propósito — não
  têm `tenant_id`, ou (no caso do audit log) são cross-tenant por
  design.
