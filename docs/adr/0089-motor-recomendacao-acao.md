# ADR-0089 — Fase 5: Motor de recomendação de ação (determinístico)

- **Status:** Aceito
- **Data:** 2026-09-07

## Contexto

Não existia, em nenhuma forma, uma camada que traduzisse um risco já
detectado numa ação recomendada concreta — o sistema mostrava números e
classificações, nunca "o que fazer". O próprio roadmap marcava esta fase
como a mais sensível do ciclo: "precisa de validação de domínio
agronômico, não só código".

Os dois exemplos de regra citados no rascunho original do roadmap ("chuva
forte prevista em ≤2h + colheita pendente" e "geada forte prevista +
cultura sensível") revelaram-se não implementáveis como estavam: não
existe, em nenhum lugar do modelo de dados, um conceito de "colheita
pendente" (estágio da lavoura) nem uma classificação de "cultura sensível"
— `Location.crop` é texto livre, sem metadado nenhum de sensibilidade.
Levado ao dono do produto antes de desenhar qualquer regra: decisão foi
substituir os dois exemplos por regras equivalentes usando apenas sinais
que o sistema já calcula, em vez de expandir o modelo de dados ou inventar
classificações agronômicas por conta própria.

## Decisões

**Catálogo de 3 regras, todas sobre sinais já existentes:**

1. **Geada severa** (`frost_temperature_c ≤ 3°C`) → considerar irrigação
   por aspersão ou cobertura das plantas.
2. **Vento forte + chuva prevista** (`wind_kmh > 40` E
   `rain_probability_percent ≥ 60`) → considerar adiar a pulverização.
3. **Estresse hídrico** (`soil_moisture_percent < 30` E `vpd_kpa > 1.6`)
   → considerar irrigação.

Escopo deliberadamente pequeno (mesma filosofia YAGNI do resto do
projeto) — 2-3 pares bem validados em vez de um catálogo grande e não
revisado.

**Reaproveita a máquina de condições da Fase 3 quase inteira.**
`engine/recommendations.py` importa `MetricSnapshot`/`AlertCondition`/
`matching_groups` de `engine/alert_rules.py` sem reimplementar nada —
mesma avaliação DNF, mesmo conjunto de métricas. Uma regra de
recomendação é literalmente uma lista de `AlertCondition` mais o texto a
mostrar quando bate. `workers/recommendation_pipeline.py` reaproveita
`gather_metric_snapshot` (a mesma função da Fase 3, sem alterações) para
coletar os sinais reais de cada local.

**Nunca uma LLM decidindo a ação.** O catálogo é puro código Python,
testável contra fixtures sintéticas, sem chamada de IA — a mesma regra já
seguida por `StormRiskEngine`/`AlertEngine` (ADR-0005/0060): uma LLM só
poderia (opcionalmente, no futuro) redigir o texto de uma recomendação já
decidida pela regra, nunca decidir qual ação recomendar.

**`RecommendedAction` sem campo de status.** Registra só que uma
recomendação foi gerada (`rule_key`, `title`, `message`, `level`,
`alert_id` opcional pro `Alert` que acompanha, quando existe um do mesmo
dia). "Recomendada/executada/ignorada/expirada" é explicitamente escopo
da Fase 6 ("Registro de execução da ação") — não antecipado aqui.

**Deduplicação por (local, regra, dia), não por ciclo.** O pipeline roda a
cada 15 minutos, mas cada regra só gera uma recomendação por local por
dia — evita inundar o usuário com a mesma recomendação repetida a cada
ciclo enquanto a condição continuar batendo.

**Endpoint próprio, não embutido no `risk-digest`.** O roadmap dava as
duas opções. Optado por `GET /locations/{id}/recommended-actions`
separado — embutir misturaria "leitura de sinal" (o que o `risk-digest`
estritamente é, ADR-0087) com "recomendação derivada", a mesma fronteira
que os ADR-0087/0088 já vinham protegendo. Nunca 404 — lista vazia é
resposta honesta.

**Web e mobile reaproveitam a superfície do risk-digest.** Não um botão
novo — `RiskDigestModal.tsx` (web) e o card do `AgroScreen` (mobile, linha
compacta por recomendação) já são os lugares onde o usuário olha "o que
está acontecendo com este talhão"; as recomendações completam essa
mesma visão, buscadas por uma chamada de API separada (o `risk-digest`
do backend continua intocado).

## Consequências

- Uma tabela nova (`recommended_actions`), tenant-scoped com RLS desde a
  migração.
- Um job Celery novo, a cada 15 minutos (dedup por dia torna uma cadência
  mais apertada desnecessária).
- Preparação direta para a Fase 6: `RecommendedAction` já existe e está
  ligada ao `Alert` de origem quando aplicável — só falta o registro de
  execução.
