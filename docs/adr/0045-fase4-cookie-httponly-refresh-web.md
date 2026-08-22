# ADR-0045 — Fase 4: refresh token via cookie HttpOnly no dashboard web

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

O backend já tinha suporte opcional a cookie HttpOnly para o refresh token
(`REFRESH_COOKIE_ENABLED`), mas o dashboard web nunca foi integrado a esse
modo: `web/src/api.ts` guardava access **e** refresh token em
`localStorage`. Qualquer XSS no dashboard teria acesso direto ao refresh
token (validade de 7 dias) e não só ao access token (15 min) — a
diferença de blast radius entre os dois é o motivo de existir cookie
HttpOnly em primeiro lugar. O app mobile continua fora deste risco (usa
`expo-secure-store`, fora do alcance de JS de página), então a mudança é
só do lado web.

## Decisão

**Backend** (`backend/app/auth/router.py`, `backend/app/core/config.py`):

- Diferenciação de cliente via header `X-Client-Platform: mobile` —
  qualquer valor ausente ou não reconhecido cai no caminho mais seguro
  (cookie), por design: um cliente não pode se auto-declarar "não use
  cookie" só omitindo o header.
- `_apply_token_response()`: se não for mobile e `REFRESH_COOKIE_ENABLED`
  estiver ligado, seta o cookie (`HttpOnly`, `Secure` em produção,
  `SameSite` configurável) e devolve `refresh_token: null` no corpo JSON —
  nunca os dois lugares ao mesmo tempo.
- `/auth/refresh` aceita o cookie sem exigir token no corpo; se corpo E
  cookie vierem juntos, corpo tem precedência (comportamento pré-existente,
  mantido e agora coberto por teste explícito — nenhum dos dois caminhos
  concede mais privilégio do que a própria assinatura do JWT já concederia).
- `/auth/logout` remove o cookie com os mesmos atributos usados na criação.
- Novo validador de config: `SameSite=None` sem `Secure=true` falha no
  startup (`ValueError`) — regra do próprio navegador, não só de produção;
  antes disso só existia a checagem "cookie deve ser Secure em produção".
- `REFRESH_COOKIE_ENABLED` virou `true` por padrão em `.env.example`.

**Frontend web** (`web/src/api.ts`, `App.tsx`, `Login.tsx`,
`Dashboard.tsx`):

- Access token só em memória (variável de módulo) — nunca mais
  `localStorage`.
- Migração de saída: na carga do módulo, remove as chaves antigas
  (`stormpulse.access_token`/`stormpulse.refresh_token`) de qualquer
  `localStorage` residual de sessões anteriores ao Fase 4.
- `initSession()`: no boot do app, tenta trocar o cookie por um access
  token via `/auth/refresh`; nunca lança — cookie ausente/expirado é um
  "faça login" comum, não uma exceção. `App.tsx` ganhou um estado
  `'checking'` para não decidir `authed`/`login` antes dessa resposta.
- Toda requisição usa `credentials: 'include'`.
- 401 dispara exatamente um refresh compartilhado (lock por promise) e
  uma única retentativa da requisição original — nunca um loop.
- `logout()`: chama o backend (best-effort) e sempre limpa o estado local
  no `finally`, mesmo se a chamada de rede falhar.

**Mobile**: sem mudança de modelo de sessão (continua corpo JSON +
SecureStore), mas `mobile/src/api.ts` passou a enviar
`X-Client-Platform: mobile` em `/auth/login` e `/auth/refresh` — sem
isso, o novo padrão `REFRESH_COOKIE_ENABLED=true` faria o backend tratar
o mobile como cliente web e omitir `refresh_token` do corpo, quebrando a
sessão do app silenciosamente em produção.

## Verificação

- Backend: 17 testes em `test_integration_auth_cookie.py` (cookie
  HttpOnly, ausência de `refresh_token` no corpo quando cookie ativo,
  cliente mobile continua recebendo o corpo, header case-insensitive,
  corpo vence cookie quando os dois vêm juntos) + 8 em `test_config.py`
  (as duas variações de `SameSite=None`/`Secure`). Suíte completa:
  89.26% de cobertura.
- Web: `npx tsc -b` limpo; `api.test.ts` reescrito (14 testes) cobrindo
  login sem tocar `localStorage`, migração das chaves antigas,
  `initSession` nos dois desfechos, refresh-e-retry em 401, 401
  concorrentes compartilhando um único refresh, cookie inválido limpando
  a sessão em vez de laçar, e `logout()` nos dois casos (rede ok/rede
  falha). Suíte inteira do `web/` (39 testes) e `npm run build` verdes.
- Mobile: `npx tsc --noEmit` limpo; teste novo em `api.test.ts` trava que
  tanto `login` quanto o fluxo de refresh mandam
  `X-Client-Platform: mobile`; suíte inteira (7 testes) verde.

## Consequências

- Em produção, o refresh token do dashboard web nunca mais fica acessível
  a JavaScript — um XSS no dashboard exporia, no pior caso, só o access
  token de 15 minutos.
- Mobile continua funcionando sem mudança de modelo, agora de forma
  explícita (header próprio) em vez de depender implicitamente do
  comportamento padrão do backend.
- Fora de escopo (deliberado, registrado como risco residual): rotação/
  revogação de refresh token com persistência em banco — o cookie atual
  ainda é um JWT stateless de 7 dias, igual ao modo body-token; revogação
  antecipada (ex.: "sair de todos os dispositivos") exigiria uma tabela
  de sessões e fica para uma fase futura.
