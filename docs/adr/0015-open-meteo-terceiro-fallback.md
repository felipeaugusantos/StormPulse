# ADR-0015 — Open-Meteo como terceiro nível de redundância

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** FASE 20 — mais uma fonte real, atrás de INMET e CPTEC

## Contexto

Você perguntou se existia outra ferramenta além do INMET, especificamente
pra cobrir os dois pontos que só ele resolve hoje: vento atual (janela de
pulverização) e histórico de chuva (sequência sem chuva/chuva acumulada) —
o CPTEC não cobre nenhum dos dois (ADR-0011/0014). Testei ao vivo o
[Open-Meteo](https://open-meteo.com) — agregador internacional gratuito,
sem chave, que combina modelos de várias agências (DWD, NOAA, ECMWF etc.,
incluindo dado sobre o Brasil).

Achado que muda uma decisão anterior: o Open-Meteo devolve **previsão
numérica real de chuva** (`precipitation_probability_max`,
`precipitation_sum`) — nem INMET nem CPTEC conseguiam isso (só texto ou
código de condição). Perguntei se isso deveria atualizar a janela de
pulverização (que era só vento por essa limitação) e você confirmou que
sim.

## Decisão

- Novo `OpenMeteoWeatherProvider` (`backend/app/weather/open_meteo.py`):
  `get_current_data`/`get_forecast` via `api.open-meteo.com/v1/forecast`
  (testado ao vivo pra Ribeirão Preto); `get_recent_rainfall` via
  `archive-api.open-meteo.com/v1/archive` — **uma chamada só** cobre
  qualquer intervalo de dias (diferente do INMET, que precisa de uma
  chamada por dia). Sem radar/avisos — honestamente indisponível, mesmo
  padrão do CPTEC.
- Licença: gratuito só para uso **não comercial** e até 10.000
  chamadas/dia. O StormPulse fica bem abaixo disso, mas é uma restrição
  real (diferente de INMET/CPTEC, que são governo/sem essa cláusula) —
  documentado aqui para o caso do projeto virar algo comercial no futuro.
- **Cadeia de fallback vira 3 níveis**: INMET → CPTEC → Open-Meteo, cada um
  tentado só quando o anterior falha, por método (mesmo
  `FallbackWeatherProvider` já existente — genérico o suficiente pra
  aninhar sem mudança nenhuma:
  `FallbackWeatherProvider(FallbackWeatherProvider(inmet, cptec),
  open_meteo)`). Dois flags independentes (`CPTEC_FALLBACK_ENABLED`,
  `OPEN_METEO_FALLBACK_ENABLED`), ambos ligados por padrão.
- **Janela de pulverização passa a considerar chuva também**: quando o
  provider ativo consegue dar `precipitation_probability` (hoje, só o
  Open-Meteo consegue — INMET/CPTEC continuam deixando `None`), a janela
  fica insegura se a probabilidade prevista pra hoje for ≥
  `AGRO_SPRAY_MAX_RAIN_PROBABILITY_PERCENT` (padrão 30%). Quando não
  disponível, o resultado continua baseado só em vento — nunca vira
  "inseguro" por falta de dado, só por dado real desfavorável.

## Consequências

- Nenhuma mudança de schema quebra compatibilidade: `ForecastPoint.
  precipitation_probability`/`precipitation_mm` já existiam (sempre
  `None` até agora) — só passam a ser preenchidos de verdade quando o
  Open-Meteo é a fonte que respondeu.
- `SprayWindowOut` ganhou `rain_probability_percent`, `rain_expected_mm`,
  `max_rain_probability_percent` — aditivo, não quebra clientes que só
  olhavam `safe`/`wind_kmh`.
- Testes: `backend/tests/test_weather_open_meteo.py` (provider isolado,
  MockTransport) + testes de fábrica atualizados pra cadeia de 3 níveis
  (`test_weather_mock.py`) + endpoint de spray-window continua verificado
  via `test_integration_locations.py`.
