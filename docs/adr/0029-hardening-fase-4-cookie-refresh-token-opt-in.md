# ADR-0029 — Hardening (Fase 4): infraestrutura de cookie HttpOnly para o refresh token (opt-in)

- **Status:** Aceito (implementação parcial — bloqueado por decisão de domínio de produção)
- **Data:** 2026-08-21
- **Contexto:** Ciclo de hardening técnico — refresh token do dashboard web fica em `localStorage`, legível por qualquer script (XSS)

## Contexto

`web/src/api.ts` guarda `access_token`/`refresh_token` em `localStorage` —
qualquer XSS no dashboard rouba o refresh token (validade 7 dias), não só
o access token (15min). Migrar pra cookie `HttpOnly` resolve isso, mas a
política correta de `SameSite`/CSRF/`Domain` depende de uma decisão que
**ainda não existe**: o dashboard web e a API vão rodar no mesmo domínio
em produção, ou em domínios/subdomínios diferentes? Perguntado
diretamente ao dono do projeto — resposta: **ainda não decidido, sem
infraestrutura de produção hoje** (só `localhost` em dev e a imagem
Docker publicada no GHCR, sem hospedagem real).

Isso é exatamente o cenário previsto no pedido de hardening: "se a
migração completa não for compatível com o deploy atual, não faça uma
implementação parcial insegura — implemente primeiro a infraestrutura
necessária e apresente a etapa restante." Esta ADR cobre só o backend,
opt-in e desligado por padrão; **o frontend web não foi tocado** — migrar
`web/src/api.ts` pra cookie sem um domínio real pra testar `Secure`/
`SameSite` seria a "implementação parcial insegura" que o pedido veta.

## Decisão

### Backend: feature completa, desligada por padrão

Settings novas em `app/core/config.py`, todas com um padrão que preserva
100% o comportamento de hoje:

```
REFRESH_COOKIE_ENABLED=false     # opt-in
REFRESH_COOKIE_NAME=stormpulse_refresh
REFRESH_COOKIE_PATH=/api/v1/auth # nunca enviado em outras rotas
REFRESH_COOKIE_SECURE=true
REFRESH_COOKIE_SAMESITE=lax      # strict|lax|none
REFRESH_COOKIE_DOMAIN=           # vazio = host-only cookie
```

Guard adicional no validator de settings: `ENVIRONMENT=production` +
`REFRESH_COOKIE_ENABLED=true` + `REFRESH_COOKIE_SECURE=false` é
**recusado no boot** (mesmo padrão já usado pro `JWT_SECRET_KEY` de dev)
— um cookie de sessão não-`Secure` em produção seria enviado em HTTP
puro.

`app/auth/router.py`: `login`/`google`/`refresh` passam por
`_apply_token_response()` — com o cookie desligado, devolvem o
`TokenPair` exatamente como sempre (nada muda); com o cookie ligado,
setam `Set-Cookie: ...; HttpOnly; ...` e **removem** `refresh_token` do
corpo JSON (`None`) — nunca os dois lugares ao mesmo tempo. `/auth/refresh`
aceita o token tanto do corpo (compat com o mobile, que nunca lê cookies)
quanto do cookie — qualquer um dos dois funciona. Endpoint novo
`POST /auth/logout` limpa o cookie (idempotente — 204 mesmo sem cookie
nenhum).

### Achado colateral corrigido: `login`/`refresh`/`logout` liam a config errada

Testando a feature com duas instâncias de app (uma com o cookie ligado,
outra não — o padrão de teste deste projeto), a settings do endpoint
**nunca refletia** a instância de teste: `login`/`refresh` usavam
`Depends(get_settings)` — o singleton `lru_cache` de processo, congelado
na primeira chamada — em vez de `Depends(get_request_settings)` (a
config real da app instanciada, `request.app.state.settings`). Isso é
exatamente o problema que a Fase 5 deste ciclo de hardening já tinha
mapeado ("corrigir especialmente: login; refresh"); antecipado aqui
porque sem isso **a própria feature desta ADR não funciona** em qualquer
cenário com mais de uma config no processo (todo o conjunto de testes de
integração, e potencialmente múltiplos workers). `login_google` já usava
`get_request_settings` (correto) — só os outros 3 pontos foram migrados
agora. O restante do escopo da Fase 5 (usuário autenticado, providers
meteorológicos, rate limiter de auth construído em import-time) continua
pendente, sem mudança nesta ADR.

### Análise de CSRF (por que não foi implementado agora)

Com `SameSite=Lax` (o padrão desta feature) e o cookie restrito a
`Path=/api/v1/auth`, a superfície de CSRF já é pequena mesmo sem um
token CSRF explícito: `SameSite=Lax` bloqueia o envio do cookie em
requisições cross-site que não sejam navegação de nível superior — um
`POST` de formulário forjado em outro site não leva o cookie. Os 3
endpoints que o usam (`login`, `refresh`, `logout`) também não têm uma
ação destrutiva explorável mesmo se um CSRF acontecesse: `login` exige
e-mail+senha no corpo (que um atacante não controla via CSRF simples),
`refresh` só emite um novo access token pro mesmo usuário já logado, e
`logout` só desloga (nunca destrutivo). **Se a topologia futura decidida
for cross-site** (domínios diferentes), `SameSite` precisa virar `none`
— nesse caso um CSRF token explícito passa a ser obrigatório antes de
habilitar em produção; isso fica para quando essa decisão existir.

## Consequências / passo restante (decisão do proprietário)

- **Não migrado:** `web/src/api.ts` continua em `localStorage`, exatamente
  como antes desta ADR — só o backend ganhou a capacidade, desligada.
- **Passo manual pendente:** quando houver um domínio de produção real,
  decidir a topologia (mesmo domínio vs. cross-site) determina
  `REFRESH_COOKIE_SAMESITE` e se um CSRF token explícito é necessário.
  Só depois disso faz sentido migrar `web/src/api.ts` pra ler o access
  token da resposta e depender do cookie automático do navegador pro
  refresh (esse é o trabalho real de frontend desta fase, ainda não
  feito).
- Testado: `tests/test_integration_auth_cookie.py` (cookie ligado —
  login seta `Set-Cookie`/omite o corpo, refresh aceita via cookie,
  logout limpa, token do refresh via cookie autentica de verdade em
  `/users/me`) e `tests/test_integration_cors.py` (origem permitida
  recebe os headers CORS+credentials, origem não permitida não recebe
  nada, preflight de origem não permitida é rejeitado). Suíte completa
  do backend re-rodada após a migração de `get_settings`→
  `get_request_settings`: 100% verde, 89.44% cobertura.
