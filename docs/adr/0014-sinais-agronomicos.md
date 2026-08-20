# ADR-0014 — Sinais agronômicos (geada, pulverização, sequência sem chuva, chuva acumulada)

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** FASE 19 — 4 ideias voltadas pro agro, pedidas por você

## Contexto

Você pediu 4 sinais voltados pro agro. Todos reaproveitam dado que o
sistema já coleta — sem fonte nova. Duas decisões de honestidade
precisaram de conversa direta com você antes de implementar.

## Decisões

### 1. "Sequência sem chuva", não "veranico"

Veranico é, tecnicamente, uma estiagem *anormal para a época do ano* —
afirmar isso exigiria normais climatológicas da região (médias históricas
de longo prazo), que o sistema não tem. O que dá pra afirmar honestamente,
com o que o INMET mede, é só "N dias consecutivos sem chuva mensurável na
estação mais próxima". É esse o nome usado em todo o sistema
(`DRY_SPELL_WARNING`, não `VERANICO_WARNING`).

### 2. Janela de pulverização é só vento — decisão sua

Nem o INMET nem o CPTEC dão probabilidade ou quantidade numérica de chuva
prevista (INMET: só resumo em texto tipo "poucas nuvens"; CPTEC: só um
código de condição tipo "pn" — ambos documentados nos ADR-0006/0011). Sem
isso, não dá pra avaliar honestamente "vai chover e lavar o produto".
Perguntei e você escolheu: o endpoint `/agro/spray-window` avalia **só o
vento atual** (`wind_gusts_kmh` quando disponível, senão `wind_kmh`) contra
`AGRO_SPRAY_MAX_WIND_KMH` (padrão 15 km/h — referência comum de risco de
deriva de pulverização). Quando a fonte não reporta vento, `safe` vem
`null`, nunca um `true`/`false` adivinhado.

### 3. Limiar de geada é genérico, não por cultura

`AGRO_FROST_THRESHOLD_C` (padrão 3.0°C) é uma referência agronômica comum
pra início de risco de geada radiativa — não foi calibrado pra nenhuma
cultura específica (café, cana e milho têm sensibilidades diferentes).
Documentado assim no código e na mensagem do alerta, não apresentado como
um número validado cientificamente pra qualquer cultivo.

### 4. Geada e sequência-sem-chuva são alertas; vento e chuva-acumulada são consulta ao vivo

Geada e sequência sem chuva são eventos discretos que fazem sentido como
notificação push (`FROST_WARNING`/`DRY_SPELL_WARNING`, mesmas tabelas
`Alert`/`Notification`, mesmo padrão de idempotência por `dedup_key` já
usado em `workers/satellite_pipeline.py`). Vento "seguro pra aplicar
agora" e "quanto choveu" são consultas pontuais — o vento muda rápido
demais pra virar alerta sem gerar ruído, e "quanto choveu" é algo que se
consulta na hora de decidir irrigar, não um evento. Por isso são endpoints
live (`GET /locations/{id}/agro/spray-window` e `.../agro/rainfall`),
mesmo padrão sem persistência de `GET /locations/{id}/forecast`.

## Implementação

- `ForecastPoint` ganhou `temperature_min_c` (não existia — o campo
  `temperature_c` sempre representou a máxima do dia, convenção herdada do
  INMET). Populado por `InmetWeatherProvider` (`temp_min` do período) e
  `CptecWeatherProvider` (tag `<minima>`).
- Novo método na interface `WeatherProvider.get_recent_rainfall` — soma
  leituras reais de chuva por dia via `InmetWeatherProvider` (reusa
  `_nearest_station`/`_fetch_station_readings` já existentes); o CPTEC
  não tem histórico, só previsão pra frente, e levanta
  `WeatherProviderUnavailableError` honestamente; `FallbackWeatherProvider`
  aplica o mesmo padrão de fallback por método já usado nos outros 4.
- `workers/agro_pipeline.py`: decisão própria (não `AlertEngine` — geada e
  sequência-sem-chuva não têm os hazards 0-1 que o engine espera). A
  contagem de sequência (`dry_streak_days`) para no primeiro *gap* nos
  dados (dia sem leitura) em vez de assumir seco — nunca inventa um valor
  pra um dia sem medição. O dia de "hoje" é sempre excluído da contagem
  (leitura parcial, subestimaria o total).
- Ciclo roda a cada 6h (Celery Beat) — geada/sequência-sem-chuva não mudam
  minuto a minuto como tempestade, e a checagem de chuva acumulada chama o
  INMET uma vez por dia solicitado por local; rodar com menos frequência é
  mais gentil com a API deles.

## Verificação

- `pytest tests/test_agro_pipeline.py` — `dry_streak_days` isolado (sem
  rede/BD) + emissão de alerta com provider falso, incluindo idempotência
  e o caso de gap nos dados.
- `test_weather_inmet.py`/`test_weather_cptec.py`/`test_weather_mock.py`/
  `test_weather_fallback.py` — `temperature_min_c` e `get_recent_rainfall`
  por provider.
- `test_integration_locations.py` — os 2 endpoints live, sucesso via mock
  provider.
- Manual: ciclo real contra o local "Casa" (Ribeirão Preto) via
  `run_agro_advisory_cycle`, endpoints via curl.
