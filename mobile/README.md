# Mobile — Aplicativo (FASE 12)

App do StormPulse em **React Native + TypeScript + Expo** (SDK 51).

Consome a API (FASES 1–10):

- **Login** (JWT), com token persistido (AsyncStorage);
- **Locais monitorados** com o **risco atual** de cada um (nível, ETA, distância)
  — rótulo `MOCK` quando os dados são simulados;
- **Alertas** ativos (nível GREEN→RED);
- **Pull-to-refresh**.

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

## Estrutura

```
App.tsx                 # gate de autenticação
src/
├── api.ts              # cliente da API + token (AsyncStorage)
├── config.ts           # API_URL (EXPO_PUBLIC_API_URL)
├── theme.ts            # cores + rótulos de nível
├── types.ts
└── screens/
    ├── LoginScreen.tsx
    └── HomeScreen.tsx  # locais + risco + alertas
```

## Próximos incrementos (mobile)

- **Mapa MapLibre** (`@maplibre/maplibre-react-native`) — requer um *dev build*
  do Expo (não roda no Expo Go), por isso ficou para o próximo incremento.
- **Notificações push (FCM)** — registro de device token e recebimento de
  alertas em segundo plano (FASE 9/13).
