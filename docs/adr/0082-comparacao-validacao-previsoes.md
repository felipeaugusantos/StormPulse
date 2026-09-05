# ADR-0082 — Fase 2: Comparação e Validação de Previsões

- **Status:** Aceito
- **Data:** 2026-09-05

## Contexto

Fase 2 do ciclo de evolução agroclimática, escopo definido pelo dono do
produto: comparar ECMWF, GFS, ICON, INMET e CPTEC, calculando MAE de
temperatura, erro/viés de precipitação, erro de vento, taxa de acerto de
chuva e Brier Score, por modelo/localidade/região/horizonte — sem
recomendar um modelo sem amostra mínima.

## Decisões

**ECMWF/GFS/ICON via Open-Meteo, sem credencial nova.** Confirmado ao vivo
(2026-09-05): `GET .../v1/forecast?models=ecmwf_ifs025,gfs_seamless,
icon_seamless` retorna as três séries lado a lado num único `daily` plano,
cada variável sufixada por modelo (`temperature_2m_max_ecmwf_ifs025` etc.),
compartilhando um `time` só — não é uma resposta aninhada por modelo. O
parsing em `OpenMeteoWeatherProvider.get_multi_model_forecast` lê
diretamente essas chaves sufixadas.

**INMET e CPTEC ficam fora da comparação numérica.** Nenhum dos dois dá
número de previsão (chuva em mm, temperatura, vento) — só condição/texto
(ADR-0011/0014) — então não há nada de numérico neles pra entrar nas
mesmas métricas (MAE, Brier Score etc. exigem um valor numérico previsto).
Continuam sendo comparados implicitamente pelas métricas de disponibilidade
já existentes (`engine/validation.py::provider_availability`), só não
entram nesta comparação de acurácia numérica.

**Verdade de campo: arquivo/reanálise ERA5 do Open-Meteo, não estação do
INMET.** O endpoint de leituras por estação do INMET está aposentado sem
token (ADR-0080). O mesmo host de arquivo já usado em produção para chuva
histórica (`get_recent_rainfall`) foi estendido
(`get_daily_observations`) com temperatura e vento — confirmado ao vivo
que o endpoint já devolve os três juntos. Não é uma observação
independente no sentido estrito (é reanálise, não uma medição direta),
mas é a fonte honesta mais completa disponível hoje — documentado
explicitamente em `ObservedDailyPoint`, nunca apresentado como "estação
meteorológica real".

**Três horizontes fixos (24h/72h/120h), não um valor contínuo.**
`HORIZON_BUCKETS_HOURS` — "desempenho por horizonte" significa os mesmos
três baldes em todo lugar, não um número de horas arbitrário que dependeu
de quando o job rodou naquele dia. A previsão diária do Open-Meteo não tem
resolução sub-diária pra comparar de outro jeito.

**Dois jobs diários separados, não um só.** `record_forecast_snapshots`
grava o que cada modelo previu; `fill_observed_values`, rodando por cima
de linhas cujo `target_date` já passou, preenche o que realmente
aconteceu. Nunca no mesmo ciclo — a data-alvo precisa ter de fato
acontecido antes de existir observação pra ela.

**Isolamento de falha por localidade, não por modelo dentro da mesma
chamada.** Os três modelos vêm de uma única chamada HTTP (`models=a,b,c`)
— dividir em 3 chamadas separadas por modelo destruiria a eficiência que
motivou usar esse parâmetro em primeiro lugar. Falha de um modelo
específico dentro da resposta (Open-Meteo omite um modelo pedido) já
degrada para campos `None` naquele modelo, nunca crash. Falha da chamada
inteira (rede/Open-Meteo fora) é isolada por localidade — uma localidade
falhando nunca impede as outras de serem processadas no mesmo ciclo
(`_snapshot_one_location`, testado isoladamente por não depender do
conteúdo real do banco de dev compartilhado).

**Endpoint por localização, não admin-only.** Ao contrário do backtesting
de alertas (ADR-0058, `app/admin/`), esta comparação é sobre o ponto
geográfico do usuário, não uma visão cross-tenant de operador —
`GET /locations/{id}/forecast-comparison`, mesma autenticação/isolamento
por tenant dos demais endpoints de `app/locations/`.

**Divisão escrita (sync, Celery) vs. leitura (async, HTTP), não um único
módulo.** `workers/forecast_comparison_pipeline.py` (dois jobs, `Session`
síncrona, mesmo padrão de `workers/agro_pipeline.py`) vs.
`app/forecast_comparison/service.py::get_model_comparison` (`AsyncSession`,
mesmo padrão de `app.admin.service.get_validation_metrics`) — os dois
lados do sistema já usam sessões de tipos diferentes; forçar um módulo só
exigiria misturar ambas ou introduzir uma ponte sync/async desnecessária.

**Amostra mínima configurável, não hardcoded.**
`settings.forecast_comparison_min_sample_size` (padrão 20, alinhado com
`engine.validation.MIN_SAMPLE_SIZE_FOR_RECOMMENDATION`) — `has_enough_
samples` no schema de saída é o sinal explícito que o frontend usa pra
nunca apresentar um modelo como "mais confiável" com poucas amostras.

## Consequências

- Nova tabela `forecast_snapshots` (tenant-scoped, RLS desde a migração
  `08c0fdcd06e8`) — cresce ~3 modelos × 3 horizontes por localidade ativa
  por dia; sem purge automático ainda (considerar numa fase futura se o
  volume incomodar).
- Dois novos jobs diários no Celery beat
  (`forecast-snapshot-daily`/`forecast-observation-fill-daily`).
- As métricas só têm dado real depois de alguns dias em produção — os
  testes usam fixtures sintéticas, não esperam acumulação real (critério
  de aceite "testes determinísticos").
- `FORECAST_COMPARISON_ENABLED=true` por padrão, mas os dois jobs são
  no-op honesto (`enabled=False`) quando `WEATHER_PROVIDER=mock` — não há
  mock honesto pra "como ECMWF/GFS/ICON se saíram de verdade".
