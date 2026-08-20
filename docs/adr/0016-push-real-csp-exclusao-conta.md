# ADR-0016 — Notificação push real, CSP e exclusão de conta

- **Status:** Aceito (Web Push, CSP, exclusão de conta) / RLS adiado
- **Data:** 2026-08-20
- **Contexto:** FASE 22 — avaliação completa do sistema apontou 5 lacunas
  implementáveis sem depender de infraestrutura externa; RLS foi a exceção

## Contexto

Uma avaliação completa do sistema (pontos fortes/fracos, nota pra teste com
terceiros) apontou a lacuna mais crítica: `Notification` só gravava
`status=PENDING` e nunca era entregue de verdade (nenhuma integração
FCM/e-mail/push existia — só o registro da intenção). Junto com isso, mais 4
melhorias: Row-Level Security no Postgres, CSP, exclusão de conta (LGPD) e
code-splitting do bundle. Duas outras (paridade do app mobile, infra de
produção com TLS real) ficaram de fora por dependerem de decisão/recursos
que a conversa não tinha no momento.

## Decisão: Web Push real (VAPID)

Escolhido Web Push (padrão do navegador, chave VAPID) em vez de Firebase
Cloud Messaging — sem conta em serviço externo, funciona em `localhost`
(contexto seguro isento do requisito de HTTPS), a infra de push é o próprio
navegador.

- Nova tabela `push_subscriptions` (`backend/app/notifications/models.py`,
  migração `d3e8f1a9c7b2`): um usuário pode ter mais de uma (multi-device).
- `Settings` ganha `vapid_private_key`/`vapid_public_key`/`vapid_subject` —
  sem chave configurada, toda notificação vira `status=SUPPRESSED` (honesto,
  nunca finge que enviou — mesmo espírito de `WeatherProviderUnavailableError`
  em outras partes do sistema).
- `backend/workers/notification_pipeline.py` — nova task Celery
  (`run_notification_delivery_task`, a cada 60s) busca `Notification`
  `PENDING`, entrega via `pywebpush` a cada subscription do usuário; sucesso
  → `SENT`; subscription expirada (404/410) → apaga a subscription e marca
  `FAILED`; sem subscription nenhuma → `SUPPRESSED`.
- Frontend: `web/public/sw.js` (service worker mínimo, só lida com `push`/
  `notificationclick`) + `web/src/push.ts` (`subscribeToPush`) + botão
  opt-in explícito no topbar (permissão de notificação exige gesto do
  usuário).

## Decisão: CSP

`backend/app/core/security_headers.py` ganha `Content-Security-Policy:
default-src 'none'; frame-ancestors 'none'` em toda resposta — exceto
`/docs`, `/redoc`, `/openapi.json` (Swagger precisa de scripts/estilos
inline pra renderizar). Como este backend só serve JSON, uma política
totalmente travada é segura em todo o resto. Fecha a lacuna documentada na
ADR-0007. Vale notar: essa CSP protege as respostas da API — a SPA em si
(servida separadamente) vai precisar da própria CSP quando tiver uma
infraestrutura de produção definida.

## Decisão: exclusão de conta (LGPD)

`DELETE /users/me` (corpo `{"confirm": true}` como trava simples) —
`backend/app/users/service.py`. Como um tenant não é garantidamente 1:1 com
um usuário (login Google pode vincular uma segunda conta ao mesmo tenant
depois), só apaga o `Tenant` inteiro se for o último usuário restante;
senão apaga só o `User` (cascata via `ondelete=CASCADE` já cobre locais,
alertas, notificações, relatos).

## Decisão: code-splitting

`maplibre-gl` (usado só dentro de `StormMap`) virou `React.lazy` via
`web/src/components/LazyStormMap.tsx` — a tela de login não paga o custo
dele. Bundle inicial caiu de 976KB para ~170KB; o chunk do MapLibre (805KB)
passou a carregar só quando o mapa realmente aparece.

## Adiado: Row-Level Security no Postgres

Tentativa completa, testada contra Postgres de verdade (não só lida no
código) — e revertida depois de dois problemas reais, descobertos um atrás
do outro:

1. `SET LOCAL app.tenant_id = :tid` não aceita bind parameter — Postgres
   recusa com erro de sintaxe (`SET LOCAL x = $1` não é válido). Corrigido
   trocando por `set_config('app.tenant_id', :tid, true)`, que é uma função
   normal e aceita parâmetro sem problema.
2. Problema mais sério: `set_config(..., true)` (escopo de transação) reseta
   para **string vazia**, não `NULL`, após o commit — e o padrão já
   existente no código de "commitar no meio da requisição e reconsultar
   depois" (`locations/service.py:create_location`, `auth/service.py`
   registro/login Google) quebra nesse ponto, porque a query seguinte roda
   numa transação nova sem o contexto de tenant setado. A correção óbvia
   (`set_config(..., false)`, escopo de sessão/conexão, sobrevive ao
   commit) troca o problema por outro: como o app usa pool de conexões, o
   valor precisa ser limpo antes da conexão voltar pro pool — testado o
   hook `PoolEvents.reset` do SQLAlchemy pra isso, e ele **não funciona de
   forma confiável com o driver asyncpg** (o evento dispara, o código
   reporta sucesso, mas o valor continua vazando pra próxima checkout da
   mesma conexão — confirmado em teste direto, reproduzido 2x).

Diante de um vazamento real de contexto entre requisições (o oposto do que
RLS deveria prevenir) descoberto via teste direto contra Postgres — não só
por inspeção de código — a decisão foi reverter tudo (migração, roles,
mudanças em `deps.py`/`auth/service.py`/`db/session.py`) e manter a
isolação só em nível de aplicação (já auditada e correta — toda query já
filtra por `tenant_id`+`user_id`, nenhum caso de IDOR encontrado). RLS fica
como trabalho futuro, precisando de mais espaço pra desenhar a reaplicação
de contexto por conexão corretamente (provavelmente via evento a nível de
`Session` do SQLAlchemy reaplicando o `set_config` a cada novo `begin()`,
em vez de depender do reset do pool).

## Consequências

- `Notification.channel`/`NotificationChannel.PUSH` — comentário
  desatualizado ("Firebase Cloud Messaging") corrigido pra refletir Web
  Push de verdade.
- Nenhuma mudança de schema quebra compatibilidade — `push_subscriptions` é
  aditiva.
- Testes: `backend/tests/test_notification_pipeline.py` (sucesso,
  subscription expirada, sem subscription — `pywebpush.webpush` mockado),
  `test_security_headers.py` (CSP presente/ausente conforme a rota),
  `test_integration_auth.py` (exclusão de conta + confirmação obrigatória).
