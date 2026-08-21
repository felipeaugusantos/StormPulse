# ADR-0023 — Paridade do app mobile: Agro, talhão e push via Expo

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 26 — usuário pediu para atualizar o app mobile (Agro, cadastro de local/talhão, push nativa) e perguntou sobre publicar na Google Play

## Contexto

O app mobile (Expo/React Native, `mobile/`) era bem mais simples que o
dashboard web: só login e uma tela lendo alertas + risco de tempestade por
local, sem cadastrar local, sem aba Agro, sem push. Para trazer paridade,
três peças foram necessárias: (1) reaproveitar `agro.ts`/`storm.ts` — pura
lógica TS sem dependência de DOM, copiável direto pro mobile; (2) permitir
criar/editar local e talhão pelo celular (mesmos endpoints do dashboard
web, já prontos desde ADR-0022); (3) notificação push nativa — mas o app
mobile não pode usar Web Push (é uma API de navegador), precisa do padrão
do Expo.

## Decisão

### Push: Expo, não Web Push

`PushSubscription` (`backend/app/notifications/models.py`) ganha
`platform` (`"web"` | `"expo"`) e `expo_push_token` (nullable, único);
`endpoint`/`p256dh`/`auth` viram nullable — uma linha só popula o par
relevante ao seu `platform`. Dois endpoints novos e paralelos aos
existentes: `POST/DELETE /users/me/push-subscription/expo` — não
reaproveitou o endpoint web porque o formato do corpo é completamente
diferente (token único vs. `endpoint`+`keys`), então uma união de schemas
só complicaria sem ganhar nada.

`workers/notification_pipeline.py` passa a ramificar a entrega por
`subscription.platform`: Web Push continua via `pywebpush` + VAPID; Expo
via uma chamada HTTP simples pra `https://exp.host/--/api/v2/push/send` —
**sem nenhuma credencial de servidor**, diferente do VAPID do Web Push.
Isso muda a semântica do campo `configured` no resumo do ciclo: antes,
ausência de VAPID abortava o ciclo inteiro (`configured=False`, nada
processado); agora `configured` só reporta se o Web Push está configurado
— uma implantação só-mobile (sem VAPID) continua entregando via Expo
normalmente, e uma assinatura web sem VAPID falha (`FAILED`) em vez de
travar o ciclo todo silenciosamente.

Token expirado/dispositivo desinstalado: Expo retorna
`details.error == "DeviceNotRegistered"` no ticket — mesmo tratamento do
Web Push 404/410 (apaga a assinatura, nunca mais tenta).

### Paridade de Agro e talhão no app

`mobile/src/agro.ts` e `mobile/src/storm.ts` são cópias diretas dos
equivalentes web — funções puras, sem `window`/DOM, portáveis sem
adaptação. `mobile/src/types.ts` e `api.ts` ganham os mesmos campos/
endpoints já expostos no dashboard web (forecast, rain-forecast, spray-
window, rainfall, CRUD de location com `parent_location_id`/`crop`).

Sem biblioteca de navegação nova — o app já trocava de tela via estado
local simples em `App.tsx` (login vs. home); a barra de abas
(Tempestade/Agro/Locais) segue o mesmo padrão manual em vez de adicionar
`react-navigation` e suas dependências, consistente com o estilo mínimo já
usado no projeto.

### Google Play

Tecnicamente viável a partir daqui via **EAS Build** (o app já é Expo
gerenciado) — mas duas coisas ficam fora do que este trabalho cobre: a
conta de desenvolvedor Google Play (taxa única, cadastro pessoal) e a
publicação em si na Play Console, que exigem a conta do usuário logada.

## Consequências

- Migração nova (`a3e8d1c6f4b2`) altera `push_subscriptions` — 3 colunas
  ficam nullable, 2 novas são adicionadas; nenhuma assinatura web existente
  quebra (todas continuam com `platform` default `"web"`).
- `test_cycle_is_a_noop_without_vapid_key` foi reescrito
  (`test_cycle_reports_web_push_not_configured_without_vapid_key`) —
  comportamento mudou de "aborta o ciclo" pra "só reporta a flag", com
  testes novos cobrindo especificamente o caso mobile-only (Expo entrega
  mesmo sem VAPID) e o caso web-sem-VAPID (falha, não trava).
