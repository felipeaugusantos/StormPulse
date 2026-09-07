# ADR-0088 — Fase 4: Janela de risco unificada ("quando pode chegar")

- **Status:** Aceito
- **Data:** 2026-09-07

## Contexto

Três conceitos de "quando" já existiam no sistema, cada um com sua
própria unidade de tempo e sua própria forma de exibição: ETA de célula
de tempestade (`eta_minutes`, minutos), dias de geada prevista (lista de
datas absolutas via `formatFrostDays`) e janela ZARC (`decendios`, 36
períodos de 10 dias no ano — nunca sequer lido pelo frontend antes desta
fase). Um levantamento prévio confirmou, além disso, que o ETA de
tempestade tinha **duas fontes independentes** já hoje: o `eta_minutes`
materializado pelo backend (`LocationRisk`/`RiskDigest`) e um ETA
calculado no cliente a partir de observações por satélite
(`web/src/storm.ts::estimateStormEta`), cada uma formatada de um jeito
diferente.

## Decisões

**Só apresentação, nenhuma mudança de backend.** Cada sinal continua
guardando sua própria unidade de tempo internamente (minutos para
tempestade, dias/decêndios para geada e ZARC) — só a forma de exibir
"quando" foi unificada. `timeUntil` (novo em `web/src/format.ts` e no
primeiro arquivo de formatação compartilhada do mobile,
`mobile/src/format.ts`) segue a mesma convenção de arredondamento já
usada em `timeAgo`: minutos crus até 1h, horas arredondadas até 24h,
dias a partir daí — nunca finge mais precisão do que a fonte realmente
tem.

**Sem "próximo evento" cross-sinal.** O roadmap pedia explicitamente essa
decisão de produto antes de implementar. O levantamento mostrou uma
tensão real: o `RiskDigest` (ADR-0087) é estritamente "leitura de dado já
materializado, nunca recalcula" — `eta_minutes` vem pronto do banco, mas
"geada em N dias" e a janela ZARC só existem hoje como cálculo AO VIVO
sobre a previsão (nos componentes de tela, não no digest). Juntar os três
numa única frase "o risco mais iminente é X" exigiria misturar essas duas
fontes, um recuo direto da fronteira que o ADR-0087 já tinha traçado
deliberadamente (a mesma razão que excluiu ZARC/umidade do solo do
digest). Decisão do dono do produto: não fazer essa síntese agora — cada
painel continua mostrando "quando" do seu próprio sinal, só que todos com
a mesma linguagem de apresentação.

**ETA de tempestade — as duas fontes, mesma apresentação.** `eta_minutes`
do `RiskDigest`/`LocationRisk` (web `RiskDigestModal.tsx`, mobile
`HomeScreen.tsx`) e o ETA calculado no cliente a partir de satélite
(`Dashboard.tsx::bestStormEtaLabel`, via `estimateStormEta`) passam a usar
`timeUntil` — mesmo texto, mas continuam sendo duas fontes diferentes
internamente (nunca confundidas uma com a outra).

**Geada — `formatFrostDaysAhead` complementa, não substitui,
`formatFrostDays`.** A lista completa de dias com temperatura continua
existindo (`LocationWeatherCard.tsx`, `AgroScreen.tsx` mobile) — a nova
função só adiciona um resumo compacto ("geada em N dias") antes da lista,
usando o dia mais próximo.

**ZARC — primeira leitura de `decendios` no frontend.** Antes desta fase
o campo nunca era lido. `formatZarcWindowAhead` (só web — mobile não tem
painel ZARC) converte o `decêndio` recomendado mais próximo numa data
usando a convenção oficial do MAPA (3 períodos de 10 dias por mês: dias
1-10, 11-20, 21-fim do mês — não um 1/36 genérico do ano), testando tanto
a ocorrência deste ano quanto do ano seguinte para nunca quebrar perto da
virada do ano.

## Consequências

- Nenhuma migração, nenhum endpoint novo — puramente frontend.
- `mobile/src/format.ts` é o primeiro arquivo de formatação compartilhada
  do lado mobile (antes, cada tela formatava data/hora inline).
- Testes novos: `timeUntil` (web e mobile), `formatFrostDaysAhead` e
  `formatZarcWindowAhead` (web).
