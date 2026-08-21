# ADR-0027 — Hardening (Fase 2): Expo SDK 51 → 57 (React 19, RN 0.86)

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** Ciclo de hardening técnico — `npm audit --omit=dev` no mobile encontrava 32 vulnerabilidades (1 crítica, 19 altas) na cadeia antiga do Expo/React Native

## Contexto

A Fase 1 (ADR-0026) mediu a baseline: `npm audit --omit=dev` em
`mobile/` (SDK 51, React Native 0.74.5) reportava **32 vulnerabilidades
(1 crítica, 19 altas, 11 moderadas, 1 baixa)**, quase todas em
`@xmldom/xmldom`, `tar`/`cacache`, `postcss`, `send`, `image-size`,
`fast-xml-parser` — dependências transitivas do **CLI/build do Expo**
(`@expo/cli`, `metro`, `@react-native-community/cli-*`), não do runtime
publicado do app. O Dependabot já tinha PRs abertos propondo bumps
isolados (`react-native` 0.74.5→0.87.0, `typescript`→7.0.2,
`expo-status-bar`→57.0.1) — **exatamente o padrão perigoso que o pedido
de hardening veta**: bumps de pacotes individuais sem coordenar com a
versão do Expo SDK quebrariam a compatibilidade entre `expo`/
`react-native`/módulos `expo-*`.

## Decisão

### Migração coordenada via ferramentas oficiais do Expo, não bumps manuais

```bash
npx expo install expo@^57.0.0   # instala o pacote expo mais recente
npx expo install --fix          # resolve TODAS as deps pra versões compatíveis
```

O Expo resolveu sozinho as versões corretas de tudo:
`react` 18.2.0→**19.2.3**, `react-native` 0.74.5→**0.86.2**,
`react-native-safe-area-context`→**5.7.0**, `react-native-maps`→**1.27.2**,
`@react-native-async-storage/async-storage`→**2.2.0**, todos os
`expo-*` (constants/device/location/notifications/status-bar)→**57.x**,
`typescript`→**6.0.3** (versão que o próprio `expo install --fix`
apontou como esperada), `@types/react`→**19.2.x** (ajustado manualmente
— é devDependency, fora do escopo de `expo install --fix`, mas precisa
acompanhar a major do `react`).

**Por que direto pro SDK 57 (o mais recente) e não uma versão
intermediária:** as vulnerabilidades altas/críticas estão todas na
cadeia de build do Expo `<57` — parar numa versão intermediária (52/54)
deixaria vulnerabilidades altas não resolvidas. `expo-doctor` validou
21/21 checks depois da migração completa, incluindo a ponta mais
arriscada (compatibilidade de peer deps entre `react`/`react-native`/
`@types/react`), então não houve necessidade de recuar.

### Ajuste manual necessário: `app.json`

`expo-doctor` acusou uma falha de schema: o campo raiz `splash` foi
descontinuado a partir de uma versão intermediária do Expo — vira um
config plugin. Corrigido:

```json
// antes
"splash": { "backgroundColor": "#0b1120" }

// depois
"plugins": [..., ["expo-splash-screen", { "backgroundColor": "#0b1120" }]]
```

Exige a dependência `expo-splash-screen` (instalada via
`npx expo install expo-splash-screen`, que já adicionou o plugin
automaticamente — só a remoção do campo raiz duplicado foi manual).

### Resultado da auditoria

| | Antes (SDK 51) | Depois (SDK 57) |
|---|---|---|
| Crítica | 1 | 0 |
| Alta | 19 | 0 |
| Moderada | 11 | 11 |
| Baixa | 1 | 0 |
| **Total** | **32** | **11** |

`npm audit --omit=dev --audit-level=high` agora sai com **exit 0** — o
job `mobile` do CI (Fase 1, ADR-0026) volta a ficar verde.

### Risco residual documentado (não corrigido — decisão deliberada)

As 11 vulnerabilidades moderadas remanescentes são **todas** a mesma
cadeia: `uuid <11.1.1` (bounds check ausente, GHSA-w5hq-g745-h8pq) via
`xcode` → `@expo/config-plugins` → `@expo/cli`/`expo-splash-screen` —
de novo, ferramentas de **build/prebuild**, nunca executadas no app
publicado (rodam só na máquina de quem builda, não no dispositivo do
usuário final). `npm audit fix --force` "corrigiria" isso instalando
**`expo@46.0.21` ou `expo-splash-screen@55.0.24`** — versões **mais
antigas** que as atuais (regressão, não correção) — confirmando que não
há fix disponível sem regredir a versão do Expo. Risco aceito:
severidade moderada, superfície de ataque é a máquina de build (CI/dev),
não o app em produção; reavaliar na próxima atualização de rotina do
Expo SDK.

### Limite de verificação

Validado neste ambiente: `npm ci`, `npm run typecheck` (limpo, zero
mudança de código de aplicação necessária — nenhuma API removida do
React 18→19 estava em uso), `npx expo-doctor` (21/21) e `npm audit`.
**Não foi possível** rodar o app de fato num dispositivo/emulador neste
ambiente (mesma limitação de rede/sandbox já documentada no README
raiz para builds Docker) — o app precisa ser aberto no Expo Go ou um
dev build real antes deste upgrade ser considerado validado em runtime,
não só em compilação.

## Consequências

- `mobile/package.json` e `package-lock.json` atualizados; nenhuma
  dependência ficou órfã (todas em uso ativo no código).
- `app.json` ganhou `expo-splash-screen` como dependência + plugin.
- README do mobile atualizado (SDK 51 → 57).
- CI (job `mobile`) volta a passar no passo de auditoria bloqueante.
- Passo manual pendente do dono do repositório: abrir o app no Expo Go
  (ou gerar um dev build) para confirmar visualmente que a splash
  screen e as telas continuam corretas após a migração de major do
  React — este ambiente não consegue fazer essa verificação visual.
