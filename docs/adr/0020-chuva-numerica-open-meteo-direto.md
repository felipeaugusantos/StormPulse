# ADR-0020 — Previsão de chuva numérica: Open-Meteo direto, sem esperar a cadeia

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 24 — bug real observado no card de Trafegabilidade

## Contexto

O card de Trafegabilidade estava sempre mostrando "sem dado suficiente pra
avaliar", mesmo com chuva acumulada e vento funcionando normalmente nos
outros cards. Investigando ao vivo (local real em Ribeirão Preto):

- `GET /locations/{id}/forecast` respondeu pelo **CPTEC** (`INMET` está
  fora do ar durante praticamente toda a sessão) — e o CPTEC nunca dá
  número de chuva prevista, só código de condição (ADR-0011/0014). Todos
  os 7 dias vinham com `precipitation_mm: null`.
- `GET /locations/{id}/agro/rainfall` respondeu pelo **Open-Meteo** (CPTEC
  não implementa `get_recent_rainfall`, então a cadeia cai pro Open-Meteo
  automaticamente ali) — por isso a chuva acumulada funcionava normal.

A causa raiz: `FallbackWeatherProvider` só avança pro próximo nível quando
o atual **lança exceção** — o `get_forecast` do CPTEC nunca lança, ele só
devolve um resultado incompleto (sem chuva). Então a cadeia parava no
CPTEC e nunca chegava no Open-Meteo pra essa chamada especificamente,
mesmo o Open-Meteo estando disponível e sendo a única das 3 fontes que
realmente dá esse número (ADR-0015).

## Decisão

Nova função `get_numeric_rain_forecast_provider(settings)`
(`backend/app/weather/factory.py`) — devolve o Open-Meteo **diretamente**,
sem passar pela cadeia INMET→CPTEC. Usada em dois lugares que precisam
saber *quanto* de chuva vem, não só a temperatura:

- `get_location_spray_window` — o fator de chuva da janela de pulverização
  (antes também ficava sempre em branco pelo mesmo motivo, só não
  aparecia como erro porque o vento sozinho já bastava pra dar um
  veredito).
- Novo endpoint `GET /locations/{id}/agro/rain-forecast` — mesmo formato
  do `/forecast`, consumido pelo frontend especificamente pra
  Trafegabilidade (`web/src/agro.ts`'s `evaluateTrafficability`).

**Continua respeitando `WEATHER_PROVIDER=mock`**: em modo mock (testes,
dev local sem rede), devolve `MockWeatherProvider` em vez do Open-Meteo de
verdade — bypassar a cadeia não significa bypassar o modo simulado, senão
os testes fariam chamada de rede real.

Mensagens de "sem dado" no frontend também ficaram mais específicas —
antes um genérico "sem dado suficiente", agora diferencia "chuva prevista
indisponível no momento (fonte ativa não fornece número)" (`unknown`, dado
realmente ausente na fonte) de "sem dado suficiente pra avaliar" (`null`,
a chamada em si falhou).

## Consequências

- Nenhuma mudança de schema quebra compatibilidade — `Forecast` já existia,
  o novo endpoint só serve o mesmo formato de outro provider.
- Teste novo garante que `get_numeric_rain_forecast_provider` devolve
  Open-Meteo pra `inmet`/`cptec`/`open_meteo`, e o mock pra `mock` —
  cobrindo exatamente o bug (chamada de rede real durante teste) que essa
  mesma correção quase introduziu.
