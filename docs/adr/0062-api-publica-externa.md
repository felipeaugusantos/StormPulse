# ADR-0062 — API pública documentada (item 1 do Radar Competitivo)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Levantamento competitivo ("Radar Competitivo") apontou 5 lacunas
implementáveis sem depender de infraestrutura externa nova. A primeira,
priorizada pelo responsável do projeto, é expor os dados de locais/risco/
alertas de uma tenant para sistemas externos do próprio cliente (ex.: ERP
agrícola, planilha de monitoramento) — hoje só existe a API interna
consumida pelo próprio frontend, protegida por JWT de curta duração.

## Decisão

### Autenticação por chave de API, não por JWT

JWT foi desenhado para sessão de usuário logado num browser (expira em
minutos, carrega em cookie). Uma integração externa roda sem usuário
sentado na frente, então precisa de uma credencial de vida longa que o
próprio usuário gerencia — o padrão de mercado (Stripe `sk_live_`, GitHub
`ghp_`) é uma chave opaca de alta entropia, hash guardado, valor bruto
mostrado uma única vez.

`app.apikeys.service.create_api_key` gera `sp_live_` +
`secrets.token_urlsafe(32)`; só o SHA-256 (`key_hash`) é persistido, mais
um prefixo curto (`key_prefix`) só para o usuário reconhecer a chave numa
lista sem poder derivar o valor completo dele. `require_api_key`
(`app/api/deps.py`) é o equivalente do `get_current_user` para essa
credencial: lê `X-API-Key`, resolve o hash, carrega o `User` dono,
aplica exatamente a mesma sequência de RLS (`bypass_rls` para o lookup
cross-tenant do hash — a tenant só é conhecida depois de resolver a
chave — depois `set_tenant_context` com a tenant do dono antes de
qualquer query de dado).

### RLS: nova tabela, migração própria

`api_keys` tem `TenantMixin`, mas nasceu depois da migração original de
RLS (`0b7b9a5dbd11`) — como migrações aplicadas nunca são editadas, a
nova migração (`d4b8e2f6a9c1`) replica a mesma sequência `ENABLE`/`FORCE
ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation` só para essa
tabela. Nenhum `GRANT` novo é necessário — o `ALTER DEFAULT PRIVILEGES`
da migração original já cobre tabelas futuras.

### Superfície exposta: só leitura, só o que o dashboard já mostra

`GET /api/v1/external/v1/locations`, `GET .../locations/{id}/risk`,
`GET .../alerts` — mesmo shape (`LocationOut`/`StormRiskOut`/`AlertOut`)
que a API interna já usa, filtrado sempre pela tenant/usuário dono da
chave (nunca cross-tenant, nunca cross-user dentro da mesma tenant: uma
chave só vê o que seu dono já veria no dashboard). Nenhum endpoint de
escrita — criar/editar local ou alerta continua exigindo login normal.
Gerência das chaves em si (`POST/GET/DELETE /users/me/api-keys`) fica no
router autenticado por JWT normal — só um usuário logado pode criar ou
revogar chaves da própria conta.

### Rate limit dedicado

`api_rate_limit_max`/`api_rate_limit_window_seconds` (`Settings`, default
60 req/60s) aplicado só ao prefixo `/external/v1` via `RateLimiter(...,
scope="external-api")` — isolado do rate limit da API interna, porque o
padrão de uso de uma integração automatizada é diferente do de um
usuário clicando no dashboard.

## Verificação

`tests/test_external_api.py` (9 testes, Postgres/Redis reais): criação/
listagem/revogação de chave; 401 sem chave, com chave desconhecida ou
revogada; isolamento entre tenants (duas contas, cada uma só vê o próprio
local pela chave); 404 de risco ainda não calculado e de local de outra
tenant; listagem de alertas. Suíte completa (`pytest --cov-fail-under=85`)
e `mypy`/`ruff` limpos após a mudança.

## Consequências

- Puramente aditivo — nenhum contrato existente muda; a API interna do
  frontend continua exatamente como era.
- Um cliente que perder o valor bruto da chave precisa gerar uma nova
  (revogar a antiga) — não há como recuperar o valor, por design (só o
  hash é guardado).
- Documentação de uso (como gerar a chave, exemplos de chamada) fica a
  cargo do Swagger automático (FastAPI já documenta os 3 endpoints
  externos via `tags=["external-api"]`); nenhum portal de docs separado
  foi criado nesta fase.
