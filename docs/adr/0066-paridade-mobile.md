# ADR-0066 — Paridade mobile (item 5 do Radar Competitivo)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Último item da sequência. Auditoria prévia (comparando `mobile/src/` com
`web/src/components/`) encontrou como ausentes no app mobile, apesar de já
existirem no backend e no web: banner de verificação de e-mail, exclusão
de conta, resumo de risco por IA, mapa visual de tempestade, e painéis de
raios/observações de satélite. Também ausentes, mas fora de escopo desta
fase por exigirem dependência nova ou tela inteira nova: relatório
semanal em PDF, painel de administração, gestão de chaves de API,
hCaptcha.

## Decisão

Tudo implementado reusa endpoints do backend já existentes e já testados
(usados pelo web) — **nenhuma mudança de backend foi necessária** para
este item.

### Mapa visual (`mobile/src/components/StormMapView.tsx`)

`react-native-maps` já era dependência do projeto, usado só em
`PlotBoundaryMapScreen.tsx` (desenho de contorno de talhão). Novo
componente reusa a mesma lib para plotar, sobre o mapa que a
`HomeScreen` já tinha só como lista: locais monitorados (marker + círculo
do raio), células de tempestade (círculo colorido por severidade,
raio proporcional a `area_km2`, callout ao toque com severidade/dBZ),
raios (círculo pequeno amarelo) e observações de satélite ativas (círculo
tracejado). Paleta de severidade idêntica à do `web/src/components/
StormMap.tsx` (`SEVERITY_COLOR`), reaproveitando as cores já definidas em
`mobile/src/theme.ts`.

Overlay raster da imagem de satélite (GOES) foi deixado de fora — exigiria
georreferenciar um PNG dinâmico no mapa nativo (`react-native-maps`
`Overlay` com um arquivo local, não bytes inline), uma peça
significativamente maior que plotar geometrias/markers; ficou junto dos
itens de esforço alto identificados na auditoria (não pedidos nesta
fase).

### Banner de verificação + exclusão de conta

`api.me()`, `api.resendVerification()`, `api.deleteAccount()` novos em
`mobile/src/api.ts` — mesmos endpoints que `web/src/api.ts` já chama
(`GET /users/me`, `POST /auth/resend-verification`,
`DELETE /users/me` com `{confirm: true}`). Confirmação de exclusão via
`Alert.alert` (padrão nativo, já usado em `LocationsScreen.tsx` para
remover local), não `window.confirm` (que não existe em React Native).

### Resumo de IA e painéis de raios/satélite

`StormRisk.ai_summary` adicionado ao tipo mobile, mostrado no card de
local quando presente (mesma condição do web:
`risk?.ai_summary && <Text>`). Raios/observações de satélite mostrados
como lista de texto (mesmo padrão já usado pros painéis de geada/
pulverização/trafegabilidade em `AgroScreen.tsx`) — não como mais uma
camada no mapa isolada, já que o mapa novo já os inclui visualmente.

## Verificação

`npm run typecheck` (tsc limpo) e `npm test` (13 testes Jest, 4 novos
cobrindo `me()`/`deleteAccount()`/`resendVerification()`/
`storms()`/`lightning()`/`satelliteWatches()` — mesmo padrão de mock de
`fetch` já usado pela suíte de sessão existente).

**Limite explícito**: não foi possível abrir um emulador Android/iOS ou
Expo Go real neste ambiente para uma verificação visual da tela
renderizada (diferente do que foi feito pra cada mudança de frontend web
nesta sessão, via browser real). A verificação aqui se apoia em:
tipagem estática correta, testes automatizados passando, e no fato de
que todo endpoint novo consumido já é usado e testado pelo lado web —
não é dado novo, é só a mesma chamada feita de um cliente diferente. Uma
verificação visual manual num device/simulador real fica pendente para
quem tiver acesso a esse ambiente.

## Consequências

- Nenhuma mudança de contrato de API — puramente consumo de endpoints
  já existentes por um cliente novo.
- Nenhuma dependência nova adicionada ao mobile.
- Overlay de satélite, relatório PDF, painel admin, chaves de API e
  hCaptcha continuam como gaps conhecidos e documentados, não
  resolvidos nesta fase — registrados aqui para uma eventual fase 2 de
  paridade.
