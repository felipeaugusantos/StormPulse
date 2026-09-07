# ADR-0086 — Fase 3: Alertas Personalizados

- **Status:** Aceito
- **Data:** 2026-09-07

## Contexto

Fase 3 do ciclo de evolução agroclimática, escopo definido pelo dono do
produto: transformar os alertas num sistema de regras operacionais
configuráveis — condições sobre chuva/vento/temperatura/geada/VPD/umidade
do solo/risco de doença/raios por distância/aproximação de tempestade,
operadores AND/OR, antecedência, horário silencioso, cooldown,
deduplicação, confirmação de recebimento, escalonamento, múltiplos canais
(e-mail, push, webhook com HMAC, abstrações WhatsApp/SMS), e uma tela de
criar/simular regras.

Um diagnóstico prévio confirmou: `Alert`/`Notification`/`AlertPreference`
continuam existindo e não foram tocados — `AlertPreference` é hoje só um
liga/desliga binário por (local, tipo), sem threshold numérico; o motor
de `app/alerts/engine.py` é hazard-score de tempestade (0-1), estrutura
totalmente diferente de um avaliador de condições configuráveis. Nenhuma
das 8 entidades pedidas tinha equivalente — a fase inteira é aditiva.

## Decisões

**Sistema paralelo, não refatoração.** `AlertRule`/`AlertCondition`/etc.
são 8 tabelas novas, tenant-scoped com RLS desde a migração
(`67c40c366af6`/`7e8060f3f148`). Os 4 pipelines existentes
(`pipeline_service.py`, `agro_pipeline.py`, `satellite_pipeline.py`,
`official_warnings_pipeline.py`) continuam emitindo `Alert`/`Notification`
exatamente como antes.

**Condições em DNF (E dentro do grupo, OU entre grupos), não uma árvore de
expressão genérica.** `AlertCondition.group_index` — mesmo grupo = AND,
grupos diferentes = OR. Cobre "vento > 40 E chuva > 10" e "geada OU vento
forte" com uma tabela só, sem precisar de uma entidade "grupo de
condições" separada. `engine/alert_rules.py::evaluate_conditions`/
`matching_groups` são funções puras, testadas com fixtures sintéticas.

**Bridge para um `Alert` real em cada transição, não um feed separado.**
Toda abertura/atualização/encerramento de `AlertEvent` cria também uma
linha em `Alert` (`event_type=CUSTOM_RULE`) — permite reaproveitar
`notification_pipeline.py::_deliver_to_subscriptions`/`_deliver_email`
inalteradas para os canais push/e-mail, e mostra o alerta personalizado no
mesmo feed `/alerts` que qualquer outro alerta. Nível de severidade:
OPEN/UPDATED usam `RiskLevel.ORANGE` (sem hazard score próprio pra
calcular uma severidade real), CLOSED usa `RiskLevel.GREEN` ("tudo
seguro", mesmo significado usado no resto do sistema).

**`AlertDelivery` por (evento, destinatário), não uma linha cobrindo todo
canal.** Diferente de `Notification` (uma linha cobre push+e-mail juntos)
— aqui cada destinatário/canal tem sua própria linha, com `attempts`/
`next_retry_at`/`status` independentes, necessário pra escalonamento e
histórico de entrega por canal serem rastreáveis separadamente.

**Verdade de campo reaproveitada do resto do sistema, dois gaps
preenchidos.** VPD e risco de doença só existiam calculados no frontend
(`web/src/agro.ts`) — portados para `engine/agro.py` (mesma fórmula
Tetens/FAO-56, mesmos limiares) porque um pipeline de regra roda sem
navegador nenhum aberto. Chuva/vento/temperatura vêm do Open-Meteo direto
(ADR-0020); raio mais próximo, de `LightningStrike` + `haversine_km`;
aproximação de tempestade, do `eta_minutes` mais recente de `StormRisk`.

**Webhook com HMAC-SHA256, mesmo primitivo já usado no projeto, chave
própria.** `app/alert_rules/providers.py::sign_webhook_payload` —
`hmac.new(secret, body, sha256)`, cabeçalho `X-StormPulse-Signature`.
Segredo guardado com `app.core.crypto.encrypt_field` (AES-256-GCM já
existente), nunca reaproveitando a chave de índice cego de PII — chaves
diferentes para propósitos diferentes, mesma regra do ADR-0055.

**WhatsApp/SMS como abstração explícita, não integração real.** O pedido
foi "abstrações", e nenhum contrato de credencial existe hoje (nem WhatsApp
Business API nem gateway de SMS). `MockWhatsAppSmsProvider` sempre levanta
`WhatsAppSmsProviderUnavailableError` — vira uma tentativa de entrega
registrada como falha (com retry), nunca um envio fingido. O que um
provider real precisaria está documentado na docstring de
`WhatsAppSmsProvider`.

**Simulação reaproveita o motor real, nunca persiste.**
`POST /alert-rules/{id}/simulate` chama a mesma
`gather_metric_snapshot`/`matching_groups` do ciclo de verdade contra o
snapshot atual do local — nenhum `AlertEvent`/`AlertDelivery`/`Alert` é
criado, confirmado por teste de integração dedicado.

**Gotcha de RLS pós-commit, já documentado no projeto, replicado
corretamente.** `set_tenant_context` usa `set_config(..., true)`
(transaction-scoped) — um `session.commit()` no meio do handler encerra
essa transação e apaga o contexto de tenant pra qualquer query seguinte
na mesma sessão. Pego ao vivo num smoke test manual (`conditions` voltava
vazio depois de criar uma regra) e corrigido com o mesmo padrão já usado
em `app/locations/service.py::create_location` — reaplicar
`set_tenant_context` logo após o commit, antes de qualquer releitura.
Coberto por teste de integração dedicado
(`test_create_rule_returns_the_conditions_back`).

## Consequências

- 8 novas tabelas + 2 migrations (uma só de valores de enum
  `notification_channel`/`alert_event_type`, outra das tabelas) — CI
  precisa aplicar ambas em sequência, já testado (upgrade/downgrade/
  upgrade).
- 3 novos jobs Celery: avaliação de regras (5 min), entrega (1 min),
  escalonamento (5 min) — mesma filosofia de "custo de no-op é um SELECT
  indexado" dos jobs existentes.
- `_TENANT_SCOPED_TABLES` (`app/core/rls.py`) cresce de 11 para 19
  entradas — todas as 8 tabelas novas incluídas desde este commit, sem
  repetir o gap já conhecido (`ndvi_images`/`deforestation_checks`) de
  fases anteriores.
- Escopo web: painel de criação/listagem/simulação de regras. Mobile:
  fora do escopo desta entrega inicial (paridade completa de UI mobile
  para regras fica para uma iteração futura, dado o tamanho já grande
  desta fase) — a API já está pronta para consumo quando isso acontecer.
