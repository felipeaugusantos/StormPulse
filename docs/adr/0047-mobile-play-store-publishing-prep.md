# ADR-0047 — Preparação técnica para publicar o app mobile na Play Store

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

`mobile/` (Expo/React Native, SDK 57) nunca teve nenhuma configuração
voltada a um build de release: sem `eas.json`, sem ícone próprio (o
Expo geraria com o ícone genérico do framework), e `app.json` tinha um
campo `extra.apiUrl` apontando pra `http://localhost:8000` que nunca é
lido em lugar nenhum do código — `mobile/src/config.ts` já usa
`EXPO_PUBLIC_API_URL` (padrão do Expo, inlined em build-time), então
aquele campo era configuração morta e enganosa, não a fonte real da URL
da API num build publicado.

Isso não bloqueava o desenvolvimento (Expo Go/dev client sempre usaram
`EXPO_PUBLIC_API_URL` corretamente), mas bloqueava qualquer build de
release: sem `eas.json`, não existe como gerar o `.aab` assinado que a
Play Store exige; sem ícone próprio, a ficha da loja ficaria com a
aparência do template do Expo.

## Decisão

- **Ícone**: gerado a partir do mesmo SVG já usado como favicon do
  dashboard web (`web/public/favicon.svg` — raio ciano `#4cc2e6` sobre
  círculo `#132234` em fundo `#0b1120`), rasterizado com Pillow (script
  descartável, não versionado) em quatro variantes:
  - `mobile/assets/icon.png` (1024×1024, quadrado cheio, sem
    arredondamento — o SO aplica a própria máscara).
  - `mobile/assets/adaptive-icon.png` (1024×1024, só o raio+círculo,
    fundo transparente, contido na zona segura ~66% central — o padrão
    Android de adaptive icon).
  - `mobile/assets/splash-icon.png` (mesma composição, pra tela de
    splash).
  - `mobile/assets/favicon.png` (48×48, alvo web do Expo).
- **`app.json`**: referencia os quatro arquivos acima; ganhou
  `android.versionCode: 1` e `ios.buildNumber: "1"` (obrigatórios pra
  qualquer build de loja); removido o `extra.apiUrl` morto.
- **`eas.json`** (novo): três perfis de build —
  - `development`: `developmentClient: true`, aponta pro backend local.
  - `preview`: gera `.apk` (instalação direta, sem passar pela loja),
    já aponta pra produção (`https://52-206-89-133.nip.io`) — serve pra
    testar o build de release de verdade antes de submeter.
  - `production`: gera `.aab` (formato exigido pela Play Store),
    também aponta pra produção, `autoIncrement: true` (EAS incrementa
    `versionCode` sozinho a cada build de produção).
  - `appVersionSource: "local"` — a versão vem do que está em
    `app.json`, sem depender de um contador remoto vinculado à conta
    EAS.
  - `submit.production.android.track: "internal"` — primeira submissão
    vai pra faixa de teste interno da Play Store, não direto pra
    produção pública.
- **Verificado com `npx expo-doctor`** (21/21 checks) e
  `npx expo config --type public` — confirma que os quatro assets
  resolvem e nenhum campo de `app.json`/`eas.json` está malformado.

## Fora de escopo (deliberado — depende de ações só o dono da conta pode tomar)

- Criar a conta de desenvolvedor no Google Play Console (taxa única,
  verificação de identidade).
- Publicar uma política de privacidade em URL pública (obrigatória —
  o app coleta e-mail e localização).
- Preencher a seção "Data safety" e o questionário de classificação de
  conteúdo no Play Console.
- Gerar/gerenciar a chave de assinatura — delegado ao Google Play App
  Signing via EAS Submit, não precisa de ação manual além de autorizar
  o EAS a fazer o upload inicial.
- Assets de ficha de loja (descrição, capturas de tela, banner).

## Consequências

- `EXPO_PUBLIC_API_URL` do build de produção aponta pro IP/nip.io atual
  do EC2 (`52-206-89-133.nip.io`) — se o domínio de produção mudar
  (ex.: um domínio próprio no lugar do nip.io), `mobile/eas.json`
  precisa ser atualizado manualmente antes do próximo build; não há
  hoje nenhum mecanismo automático ligando os dois.
- Um build de release (`eas build --profile production --platform
  android`) e a submissão (`eas submit`) continuam sendo ações que só
  o dono da conta EAS/Play Console pode disparar — nada aqui os
  automatiza.
