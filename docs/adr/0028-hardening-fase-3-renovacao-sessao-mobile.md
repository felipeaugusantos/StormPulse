# ADR-0028 — Hardening (Fase 3): renovação de sessão e SecureStore no mobile

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** Ciclo de hardening técnico — o app mobile guardava só o access token (`AsyncStorage`, expira em 15min), derrubando a sessão do usuário a cada 15 minutos de uso ativo

## Contexto

`mobile/src/api.ts` só persistia `access_token` (via `@react-native-async-storage/async-storage`, disco não criptografado) e nunca usava o `refresh_token` que `POST /auth/login` já retorna há tempos — o dashboard web (`web/src/api.ts`) já resolve exatamente esse problema desde antes deste ciclo de hardening (par de tokens + fila de refresh compartilhada), mas o mobile nunca replicou o padrão.

## Decisão

### Armazenamento: `expo-secure-store`, não `AsyncStorage`

Novo módulo `mobile/src/authStorage.ts` concentra toda leitura/escrita de
token via `expo-secure-store` (Keystore no Android, Keychain no iOS —
criptografado em repouso, ao contrário do `AsyncStorage`, que é disco
plano). `@react-native-async-storage/async-storage` foi **removido** do
`package.json` — não sobrou nenhum outro uso dele no código (só guardava
token).

### Fluxo de renovação — mesmo padrão do web, portado

`mobile/src/api.ts` reescrito seguindo exatamente a lógica já validada em
`web/src/api.ts`:

- Numa resposta 401 de qualquer endpoint **não-`/auth/*`**, tenta renovar
  o token exatamente uma vez (`refreshAccessToken()`) e repete a chamada
  original (`isRetry` evita um segundo retry infinito).
- **Lock compartilhado** (`refreshInFlight`, uma promise module-level):
  múltiplos 401 concorrentes (ex: várias telas buscando dados em paralelo
  no boot do app) resultam numa **única** chamada a `/auth/refresh` — os
  demais chamadores esperam a mesma promise.
- `/auth/login` e `/auth/refresh` **nunca** disparam o próprio fluxo de
  renovação (`isAuthEndpoint` checa o path) — uma senha errada é um 401
  de verdade, não uma sessão expirada; e renovar dentro do próprio
  refresh recursaria infinitamente.
- Refresh falho (refresh token inválido/expirado) limpa a sessão
  (`authStorage.clearTokens()`) e propaga o erro — quem chamou vê um
  `ApiError(401)` e decide deslogar (as 3 telas já faziam isso, só
  trocaram `clearToken()` por `logout()`).
- `App.tsx` no boot agora pergunta `hasSession()` (há um refresh token
  válido?) em vez de `loadToken()` (havia um access token não-expirado?)
  — a diferença importa: um access token de 15 min quase sempre já
  expirou fisicamente se o app ficou fechado por um tempo, mas isso não
  significa que a sessão acabou — o próprio fluxo de request+401+refresh
  cuida disso na primeira chamada real.

### Testes novos (`mobile/src/__tests__/api.test.ts`, Jest + `jest-expo`)

Nenhuma infraestrutura de teste existia no mobile antes — `jest-expo` +
`@types/jest` adicionados (só devDependencies, fora do escopo do audit
bloqueante de runtime). `expo-secure-store` é substituído por um fake em
memória (`mobile/__mocks__/expo-secure-store.ts`) nos testes — nunca toca
Keystore/Keychain de verdade. 6 testes, todos os cenários pedidos:
login+persistência, access token expirado (1 refresh + 1 retry),
múltiplos 401 concorrentes (1 única chamada de refresh confirmada),
refresh inválido (sessão limpa, erro propagado), logout, e login nunca
recursando pro próprio refresh.

### Ajuste de schema em `app.json`

`npx expo install expo-secure-store` adicionou o plugin automaticamente.
Nenhum campo manual a mais foi necessário (diferente do `expo-splash-screen`
na Fase 2, que exigiu mover um campo raiz deprecado).

## Consequências

- `mobile/package.json`: `@react-native-async-storage/async-storage`
  removido; `expo-secure-store`, `jest`, `jest-expo`, `@types/jest`
  adicionados.
- CI (`ci.yml`, job `mobile`): novo passo `npm test -- --ci`, depois do
  typecheck.
- Nenhum log em nenhum ponto do código toca token (`grep console.`
  no mobile inteiro: zero ocorrências).
- **Critério de aceite confirmado:** com o refresh token ainda válido
  (7 dias), uma sessão não cai mais aos 15 minutos — o 401 do access
  token expirado é resolvido de forma transparente antes do usuário
  perceber. Refresh inválido encerra a sessão de forma previsível
  (mesmo `ApiError(401)` que qualquer outra falha de auth, tratado pelas
  telas exatamente como antes).
- Verificado: `npm ci`, `npm run typecheck`, `npm test`, `npx expo-doctor`
  (21/21), `npm audit --omit=dev --audit-level=high` (exit 0) — todos
  limpos após uma reinstalação do zero (`rm -rf node_modules && npm ci`),
  simulando o ambiente do CI.
