# ADR-0021 — Instabilidade (CAPE), ETA de tempestade, rajada prevista, balanço hídrico, graus-dia, risco de doença e VPD

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 25 — pesquisa de sinais adicionais aproveitáveis do Open-Meteo, aplicados a pedido do usuário ("Aplicar tudo")

## Contexto

Depois da correção da Trafegabilidade (ADR-0020), ficou claro que o
endpoint `/agro/rain-forecast` — sempre Open-Meteo, nunca INMET/CPTEC — dá
acesso a um conjunto de agregados diários que o sistema ainda não usava:
CAPE máximo, ET0 (evapotranspiração de referência), umidade média/máxima,
temperatura média e rajada de vento máxima prevista. Todos confirmados ao
vivo via `curl` direto em `api.open-meteo.com/v1/forecast` antes de
qualquer código ser escrito (mesma disciplina das fases anteriores).

## Decisão

**Backend** — `ForecastPoint` (`backend/app/weather/provider.py`) ganhou 6
campos novos, todos opcionais: `temperature_mean_c`, `humidity_mean_percent`,
`humidity_max_percent`, `wind_gusts_max_kmh`, `evapotranspiration_mm`,
`cape_max_jkg`. Populados em `OpenMeteoWeatherProvider.get_forecast`
(único provider que realmente tem esses números) e em
`MockWeatherProvider` (determinístico, mesmo padrão de `_wave`).
INMET/CPTEC não mudam — continuam deixando `None`, mesma regra de honestidade
das fases anteriores (nunca aproximar um dado que a fonte não tem).

**Frontend** — 7 sinais derivados, todos client-side e computados a partir
de `rainForecast` (Open-Meteo garantido, ADR-0020), nunca persistidos:

1. **CAPE / instabilidade** (`web/src/storm.ts`, `classifyCape`) — 4 níveis
   (fraca/moderada/forte/extrema), mesmos limiares que a própria REDEMET
   usa (Fraca/Moderada/Forte/Extremo). Novo card "🌩️ Instabilidade" na aba
   Tempestade, e linha no card de clima do local selecionado.
2. **ETA de tempestade** (`web/src/storm.ts`, `estimateStormEta`) —
   projeção linear a partir de `ConvectiveWatch.speed_kmh`/`direction_deg`
   (já calculado pelo pipeline de satélite) + distância haversine até cada
   local monitorado. Omitido (não um número errado) quando a célula não
   está indo na direção do local (>45° de desvio) ou não tem
   velocidade/direção — mesma filosofia de "sem dado é `null`, não um
   palpite". Exibido inline nas linhas de observação via satélite.
3. **Rajada de vento prevista** — linha nova no card de clima do local
   (`wind_gusts_max_kmh` de hoje), complementando a rajada atual que já
   existia em `CurrentConditions`.
4. **Balanço hídrico** (`web/src/agro.ts`, `waterBalanceMm`) — chuva menos
   ET0 do dia. Novo card "💧 Balanço hídrico" na aba Agro.
5. **Graus-dia (GDD)** (`growingDegreeDays`) — `max(0, temp_média - base)`,
   base genérica de 10°C (não por cultura, mesma filosofia dos limiares de
   geada/seca já existentes). Mesmo card que o balanço hídrico.
6. **Risco de doença fúngica** (`classifyDiseaseRisk`) — proxy diário
   simplificado: umidade média ≥80% e temperatura média entre 15–30°C.
   Aproximação intencional — um modelo real precisaria de
   horas-consecutivas-acima-do-limiar, que a granularidade diária do
   forecast não permite. Novo card "🦠 Risco de doença" na aba Agro.
7. **VPD — déficit de pressão de vapor** (`vaporPressureDeficitKpa`,
   `classifyVpd`) — fórmula de Tetens/FAO-56, 3 faixas (baixo/ideal/alto).
   Mesmo card que o risco de doença.

Todos os 6 novos campos numéricos ficam concentrados numa única função,
`deriveAgroSignals` (`Dashboard.tsx`), aplicada ao primeiro ponto futuro do
`rainForecast` de cada local — evita duplicar a lógica de derivação entre
o painel do dashboard e o card de clima do local selecionado (que já lê os
mesmos campos diretamente do seu próprio `rainForecast`).

## Consequências

- Nenhuma migração de banco — tudo é DTO + cálculo client-side, mesma
  filosofia de `agro.ts` desde a FASE 18.
- `ForecastPoint` cresce mas de forma retrocompatível (campos opcionais);
  nenhum consumidor existente quebra.
- Testes novos cobrem a população dos 6 campos tanto no mock quanto no
  Open-Meteo real (`tests/test_weather_mock.py`,
  `tests/test_weather_open_meteo.py`).
- CAPE/ET0/umidade/rajada só existem quando a fonte ativa é Open-Meteo
  (direto, via `rain-forecast`) — os cards mostram "indisponível" nos
  outros casos, nunca um número inventado.
