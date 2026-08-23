# ADR-0048 — Painel de operador da plataforma (cross-tenant), Fase 1

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

Até agora, a única forma de ver quais clientes/usuários existem na base
era acesso direto ao banco (`psql`). O StormPulse é multi-tenant — cada
conta pertence a um `Tenant`, e o role `UserRole.ADMIN` já existente é
**escopado dentro de um tenant** (um admin de uma empresa só deveria ver
os dados da própria empresa). O pedido era diferente: uma visão de
**operador da plataforma** — só o dono do StormPulse enxergando todos os
tenants/usuários da base inteira. Isso é um nível de permissão
ortogonal ao `role` existente, não uma extensão dele.

## Decisão

**Novo flag, não uma nova role**: `User.is_platform_admin: bool`
(default `false`), separado do `role` tenant-scoped. Um usuário pode ser
`role=user` no próprio tenant e ainda assim ser operador da plataforma —
os dois conceitos não se misturam.

**Bootstrap via variável de ambiente** (`PLATFORM_ADMIN_EMAIL`): a cada
subida da API, se configurada, promove a conta com esse e-mail — **só
se ela já existir** (nunca cria uma conta). Idempotente, roda no
`lifespan` do FastAPI. Consequência aceita: promover alguém que ainda
não se cadastrou não tem efeito imediato — precisa registrar a conta
primeiro e esperar a próxima subida da API (na prática, o próximo
deploy, já que a API reinicia a cada deploy de qualquer forma).

**Guard novo, `require_platform_admin`** (`app/api/deps.py`) —
deliberadamente distinto de `require_admin` (que só olha `role`). Um
admin comum de tenant que tentar acessar `/admin/*` recebe 403 igual a
qualquer outro usuário.

**Endpoints (só leitura nesta fase)**:
- `GET /api/v1/admin/users` — lista cross-tenant, paginada
  (`limit`/`offset`, cap de 200), busca por e-mail (`search`, substring
  case-insensitive). Cada item carrega `tenant_name` — o objetivo é
  exatamente contextualizar de qual cliente é cada usuário.
- `GET /api/v1/admin/tenants` — mesma paginação/busca (por nome),
  agregando `user_count`/`location_count` por tenant via subquery com
  `GROUP BY`, não N+1.

**Frontend**: botão "🛠️ Admin" no topbar do dashboard, condicionado a
`me.is_platform_admin` — para qualquer outro usuário, o botão
simplesmente não é renderizado (confirmado nunca aparecer no DOM, não
só escondido via CSS). Ao clicar, substitui o dashboard por um painel
com abas Usuários/Tenants, busca e lista — reutiliza os componentes
visuais já existentes (`.panel`, `.row`, `.badge`) em vez de introduzir
um sistema de tabela novo.

## Fora de escopo desta fase (deliberado)

- Mutações: ativar/desativar conta, promover/rebaixar role, trocar
  `is_platform_admin` de outra conta. Fase 2.
- Log de auditoria das ações administrativas. Fase 2 (junto com as
  mutações — não faz sentido logar ações que ainda não existem).
- Métricas agregadas (usuários ativos últimos 7/30 dias, etc.). Fase 3.
- Revogação forçada de sessão — depende de uma tabela de sessões que
  ainda não existe (risco residual já registrado no ADR-0045).

## Verificação

- Backend: 7 testes novos em `test_integration_admin.py` (contra
  Postgres/Redis reais) — usuário comum recebe 403 nos dois endpoints;
  o bootstrap promove uma conta já registrada mas nunca cria uma conta
  inexistente; operador vê usuários/tenants de fora do próprio tenant;
  busca filtra corretamente; contadores de usuário/local por tenant
  batem. `ruff`/`mypy`/suíte completa (91% cobertura) verdes.
- Web: `tsc -b`, suíte de testes e `npm run build` verdes. Verificado em
  navegador real contra a stack local: registrado um usuário, reiniciada
  a API com `PLATFORM_ADMIN_EMAIL` apontando pra ele, confirmado que
  **só essa conta** vê o botão "🛠️ Admin" (uma segunda conta comum,
  logada na mesma aba, não vê o botão em lugar nenhum) e que a página
  lista corretamente usuários/tenants de vários tenants diferentes, com
  busca e contadores funcionando.
- Confirmado também no backend, direto por `curl`, que uma conta comum
  recebe `403` de `/api/v1/admin/users` mesmo sem passar pela UI — a
  proteção não depende do frontend esconder o botão.

## Consequências

- Primeira vez que existe alguma visão administrativa cross-tenant no
  sistema — a partir de agora, `PLATFORM_ADMIN_EMAIL` é uma credencial
  sensível: qualquer conta promovida enxerga e-mails, nomes e contagens
  de todos os clientes da base. Deve ser tratada com o mesmo cuidado que
  `JWT_SECRET_KEY`.
- Sem mutação nesta fase, o painel não corre o risco de um operador
  alterar dados de um cliente por engano — o próximo passo natural
  (Fase 2) precisa vir com confirmação explícita e auditoria desde o
  primeiro commit, não como retrofit.
