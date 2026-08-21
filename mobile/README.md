# Mobile — Aplicativo

App do StormPulse em **React Native + TypeScript + Expo** (SDK 51).

Três abas, paridade com o dashboard web:

- **⛈️ Tempestade** — locais monitorados com o **risco atual** (nível, ETA,
  distância) e alertas ativos (nível GREEN→RED); rótulo `MOCK` quando os
  dados são simulados.
- **🌾 Agro** — geada, pulverização, chuva acumulada, trafegabilidade,
  balanço hídrico, graus-dia, risco de doença, VPD, CAPE e rajada prevista,
  por local (mesmas funções puras de `web/src/agro.ts`/`storm.ts`, portadas
  verbatim).
- **📍 Locais** — cadastrar/remover fazenda e talhão (com cultura e cor no
  mapa), buscar cidade, usar a localização atual, e desenhar o contorno do
  talhão num mapa de satélite (`react-native-maps`).

Login (JWT, token persistido via AsyncStorage) e notificação push nativa
(Expo push token, registrado no backend) completam o app.

## Rodando

```bash
npm install
EXPO_PUBLIC_API_URL=http://SEU_IP:8000 npm start
```

Abra no **Expo Go** (Android/iOS) escaneando o QR code. Use um usuário criado
via `POST /api/v1/auth/register`. Em dispositivo físico, aponte
`EXPO_PUBLIC_API_URL` para o IP da máquina que roda a API (não `localhost`).

```bash
npm run typecheck   # tsc --noEmit (validado no CI)
```

### Mapa (`react-native-maps`)

Funciona no Expo Go sem configuração extra para desenvolvimento. Para um
**build de produção Android** (EAS Build), é necessária uma chave da Google
Maps API — adicione em `app.json`:

```json
"android": { "config": { "googleMaps": { "apiKey": "SUA_CHAVE" } } }
```

iOS usa Apple Maps nativamente (`mapType="standard"`/`"satellite"`), sem
chave necessária em nenhum ambiente.

## Estrutura

```
App.tsx                        # gate de autenticação + abas
src/
├── api.ts                     # cliente da API + token (AsyncStorage)
├── config.ts                  # API_URL (EXPO_PUBLIC_API_URL)
├── theme.ts                   # cores + rótulos de nível
├── types.ts
├── agro.ts / storm.ts         # lógica pura (portada do web)
├── cropColors.ts              # cor por cultura + paleta de swatches
├── geocode.ts                 # busca/geocodificação reversa (Nominatim)
├── push.ts                    # registro de push via Expo
└── screens/
    ├── LoginScreen.tsx
    ├── HomeScreen.tsx         # aba Tempestade
    ├── AgroScreen.tsx         # aba Agro
    ├── LocationsScreen.tsx    # aba Locais
    └── PlotBoundaryMapScreen.tsx  # desenho do contorno do talhão
```
