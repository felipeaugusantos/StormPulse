# ADR-0051 — Painel de operador: métricas agregadas (Fase 3)

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

Últimos itens do escopo original do painel de operador (ADR-0048):
contadores gerais da base e usuários ativos nos últimos 7/30 dias. Não
existia nenhuma noção de "usuário ativo" no sistema — `User` só tinha
`created_at`/`updated_at` (o segundo muda em qualquer UPDATE, não só
login, então não serve pra medir atividade real).

## Decisão

**Nova coluna `users.last_login_at`** (nullable — `NULL` pra quem nunca
logou desde que a coluna existe, incluindo contas recém-cadastradas).
Atualizada em exatamente dois pontos, ambos em `auth/router.py`, logo
após confirmar a autenticação: `/auth/login` e `/auth/google`. **Nunca**
em `/auth/refresh` — refresh acontece automaticamente em segundo plano
(a cada abertura do app, via `initSession`), não é uma ação deliberada
do usuário, e contá-lo como "login" infla artificialmente os números de
atividade.

**`GET /api/v1/admin/stats`** — seis contadores simples, sem quebra por
tenant (isso já é o que `/admin/tenants` mostra): `total_tenants`,
`total_users`, `active_users_7d`, `active_users_30d`,
`total_locations`, `alerts_last_30d`.

**Frontend**: nova aba "Métricas" — a primeira que aparece ao abrir o
painel (antes era "Usuários"), grade de cards com os seis números. A
lista de usuários também passou a mostrar "último login" (ou "nunca")
por linha, reaproveitando o mesmo campo.

## Verificação

- Backend: 3 testes de integração novos — 403 pra não-operador;
  `last_login_at` fica `null` até o primeiro login e é preenchido depois
  (confirmado consultando `/admin/users` antes/depois); `/admin/stats`
  reflete corretamente os contadores após criar tenants/locais e um
  login recente. Suíte completa (91% cobertura), ruff e mypy verdes.
  Confirmado também que as suítes de auth existentes (`test_integration_auth*`)
  continuam passando — `_touch_last_login` não muda nenhum comportamento
  de autenticação, só grava um timestamp a mais.
- Web: `tsc -b`, suíte de testes e `npm run build` verdes. Verificado em
  navegador real contra a stack local: aba Métricas mostra os seis
  contadores com números reais; aba Usuários mostra "último login" com
  data/hora ou "nunca" corretamente.

## Consequências

- Com as três fases completas, o painel de operador cobre o escopo
  original inteiro do ADR-0048: visão cross-tenant, mutações auditadas,
  métricas agregadas.
- `last_login_at` fica disponível pra qualquer necessidade futura além
  dessa métrica (ex.: notificar contas inativas há muito tempo), mas
  isso é território de uma fase futura, não implementado aqui.
