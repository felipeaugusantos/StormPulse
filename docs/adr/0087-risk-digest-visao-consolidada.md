# ADR-0087 — Fase 3-A: Visão consolidada de risco por talhão (`risk-digest`)

- **Status:** Aceito
- **Data:** 2026-09-07

## Contexto

Cada sinal (tempestade, geada, seca, ZARC, NDVI, desmatamento, umidade do
solo) tem hoje seu próprio painel/endpoint, sem lugar único que responda
"qual risco ameaça ESTE talhão agora". Esta fase adiciona um endpoint
agregador, `GET /locations/{id}/risk-digest`, lendo apenas resultados já
materializados — sem recalcular nada.

Um diagnóstico prévio mapeou cada sinal e encontrou três que não se
encaixam na premissa original "leitura pura de tabela por talhão":
geada/seca só existem como `Alert` emitido quando o pipeline decide
avisar (nunca um "sem risco agora" persistido); ZARC é resolvido via
geocodificação HTTP ao vivo, não uma tabela por local; umidade do solo
não tem tabela nenhuma — é sempre uma chamada de provider (NASA POWER ou
mock). Essas três decisões foram levadas ao dono do produto antes de
desenhar o schema.

## Decisões

**Tempestade, NDVI e desmatamento: leitura direta do último registro já
calculado**, mesmo padrão dos endpoints `/risk`, `/agro/ndvi` e
`/agro/deforestation` já existentes (`app/locations/service.py::
build_risk_digest`) — nenhuma query nova além de "top 1 por
`location_id`, ordenado pelo timestamp do sinal".

**Geada e seca: `frost_last_alert`/`dry_spell_last_alert`, assimétricos e
deliberadamente históricos.** Reportam o último `Alert` desse tipo já
emitido para o talhão (`occurred_at`, `level`, `title`, `message`) —
`None` significa "nunca disparou", nunca "seguro agora". O schema
(`LastAlertOut`) documenta essa diferença explicitamente para não ser
confundido com os outros sinais, que têm de fato um "estado atual".
Decisão do dono do produto: aceitar essa assimetria em vez de recalcular
geada/seca ao vivo no backend (que duplicaria a lógica que hoje só existe
no cliente, `web/src/agro.ts::classifyFrostDays`) ou excluir os dois
sinais da fase.

**ZARC excluído do digest.** É calendário de referência agronômica
resolvido por geocodificação HTTP a cada request
(`app/locations/zarc_service.py::get_zarc_window`), não um "risco que
ameaça agora" no mesmo sentido dos outros sinais — incluir quebraria a
premissa de latência previsível do endpoint agregador. Continua exposto
normalmente pelo endpoint próprio (`/agro/zarc-window`).

**Umidade do solo incluída com chamada ao vivo, mesmo padrão do
relatório semanal.** Sem tabela de persistência, a única forma honesta de
reportar esse sinal é chamar o provider na hora — reaproveita
exatamente a mesma lógica de `build_weekly_report` (try/except silencioso,
nunca falha o digest inteiro se o provider cair). Essa lógica (e a de
desmatamento) foi extraída para `_gather_soil_moisture`/
`_gather_deforestation`, compartilhadas entre os dois endpoints — mesmo
comportamento, uma só fonte de verdade.

**Nunca 404.** Diferente de `/risk`, o digest sempre responde 200 — um
talhão novo sem nenhum ciclo de pipeline rodado ainda tem todos os campos
`None`, que é uma resposta honesta e útil (não um erro).

**Sem migração de schema.** Camada de leitura pura sobre tabelas e
providers já existentes.

**Web: modal dedicado; mobile: linha resumida no card, sem modal.**
Levantamento confirmou que o mobile não tem nenhum precedente de `Modal`
(nem para telas cheias — a navegação é troca de estado local, ver
`PlotBoundaryMapScreen`) e que a Fase 2 (comparação de modelos) já tinha
tomado exatamente essa decisão para o mesmo tipo de tela: "detalhamento
completo fica só na web... mobile intencionalmente mais compacto"
(`AgroScreen.tsx::forecastComparisonSummary`). O risk-digest segue o
mesmo padrão (`riskDigestSummary`) em vez de introduzir o primeiro modal
do app mobile — consistência de precedente pesou mais que paridade
literal de UI.

## Consequências (paridade mobile)

- `mobile/src/types.ts`/`api.ts` ganham os mesmos tipos e o mesmo método
  `riskDigest` do web.
- `AgroScreen.tsx` busca o digest junto dos outros sinais já buscados por
  local e mostra uma linha resumida (⚠️ quando tempestade está
  laranja/vermelha ou há alerta de desmatamento) — sem tela nova.
- Sem testes de renderização no mobile (não há
  `@testing-library/react-native` instalado no projeto) — coberto apenas
  no nível de `api.riskDigest()` (mesmo padrão de
  `api.forecastComparison()`).

## Consequências

- `app/locations/service.py` ganha `build_risk_digest` mais dois helpers
  reaproveitados por `build_weekly_report` (comportamento idêntico ao de
  antes, coberto pelos testes já existentes de relatório semanal).
- Web: card "Risco consolidado" por talhão, reaproveitando componentes de
  exibição já existentes por sinal.
- Geada/seca no digest podem divergir do que a aba Agro mostra hoje (que
  recalcula ao vivo) — tensão conhecida e documentada, não um bug; uma
  eventual unificação fica para uma fase futura.
