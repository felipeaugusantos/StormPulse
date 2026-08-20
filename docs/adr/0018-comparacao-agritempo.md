# ADR-0018 — Comparação com o Agritempo: geada em dois níveis, trafegabilidade e inversão térmica

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** FASE 22 (continuação) — comparação com o Agritempo (Embrapa/INMET)

## Contexto

Você pediu pra analisar o [Agritempo](https://www.agritempo.gov.br/br/) —
sistema nacional de monitoramento agrometeorológico (Embrapa/INMET/CPTEC) —
e ver o que dava pra aplicar no StormPulse. É organizado em mapas por
estado/município (Monitoramento, Previsão, Índice de Seca SPI), sem API
pública documentada — não serve como nova fonte de dado redundante (nosso
sistema é por ponto/local, o deles é grade/mapa), mas trouxe 3 ideias de
funcionalidade aplicáveis com o dado que já temos (INMET/CPTEC/Open-Meteo),
sem precisar de fonte nova:

## Decisão 1: Geada em dois níveis (severa/leve)

O Agritempo separa a previsão de geada em dois limiares de temperatura
(3°C e 6°C) por vários horizontes (24-120h). Aplicado aqui como:

- `Settings.agro_frost_light_threshold_c` (novo, padrão 6.0°C) ao lado do
  já existente `agro_frost_threshold_c` (3.0°C).
- `workers/agro_pipeline.py` ganha `classify_frost_days()` (função pura,
  testada isoladamente): separa os dias da previsão em severo
  (`temperature_min_c <= 3°C`) e leve (`3°C < min <= 6°C`). Um único alerta
  por local por dia lista todas as datas afetadas e o nível de cada uma —
  antes era só um sim/não pra "algum dia com geada".
- Nível do alerta acompanha a severidade: `RiskLevel.RED` se houver algum
  dia severo, `RiskLevel.YELLOW` se só houver dias leves.
- Frontend: `web/src/agro.ts` reimplementa `classifyFrostDays` (mesma
  lógica, client-side) — usado no `LocationWeatherCard` e no `AgroPanel`
  do `Dashboard.tsx` pra mostrar a lista de dias por nível, não só um
  aviso genérico.

## Decisão 2: Trafegabilidade do solo (manejo/colheita)

O Agritempo tem uma camada dedicada de "condições para colheita"/"manejo
do solo". Sem modelo de solo próprio, aproximado como um sinal 100%
derivado do dado que já buscamos pro card de chuva acumulada e pra janela
de pulverização — nenhuma fonte nova, nenhum endpoint novo:

- `web/src/agro.ts`: `evaluateTrafficability(rainfallDaily, forecast,
  {requiredDryDays, rainThresholdMm, lookaheadDays})` — solo considerado
  seco quando há uma sequência recente sem chuva (reimplementação
  client-side de `dry_streak_days`, mesmo critério do backend) **e** não
  há chuva significativa prevista nos próximos dias. Dado de chuva futura
  ausente (INMET/CPTEC não dão isso) nunca é tratado como "sem chuva" —
  vira `'unknown'`, oculto na UI, nunca um falso "favorável".
- Puramente client-side por decisão: já é dado 100% disponível no
  navegador (rainfall + forecast já buscados), sem necessidade de mais uma
  chamada ou de persistir mais um alerta — mesmo espírito de "sinal ao
  vivo, não alerta" já usado pra janela de pulverização.

## Decisão 3: Umidade e risco de inversão térmica na janela de pulverização

A camada fitossanitária do Agritempo também pesa umidade relativa —
vento calmo + umidade alta é a assinatura clássica de inversão térmica
(comum ao amanhecer), que faz o produto pulverizado ficar suspenso no ar
em vez de se depositar na cultura (deriva).

- `CurrentConditions` (`app/weather/provider.py`) ganha
  `relative_humidity_percent`. Populado por Open-Meteo
  (`relative_humidity_2m` já vinha disponível no endpoint `current`, só
  não era pedido), INMET (`UMD_INS` da estação mais próxima) e mock.
  CPTEC continua não fornecendo `get_current_data` (nunca fingiu ter dado
  de estação pontual — ADR-0011).
- Novos `Settings.agro_spray_inversion_max_wind_kmh` (3.0 km/h — vento
  praticamente calmo) e `agro_spray_inversion_min_humidity_percent` (90%).
  `get_location_spray_window` (`app/locations/router.py`) passa a marcar
  `inversion_risk=true` quando ambas as condições se confirmam
  simultaneamente, usando o vento **médio** (não rajada — uma rajada não
  significa que o ar está se misturando).
- `SprayWindowOut` ganha `humidity_percent`/`inversion_risk`. `safe` agora
  também considera `not inversion_risk`, e a mensagem de "condição
  desfavorável" diferencia inversão térmica de vento/chuva.

## Consequências

- Nenhuma mudança de schema quebra compatibilidade — todos os campos são
  aditivos (`SprayWindowOut`, `CurrentConditions`).
- Testes: `test_agro_pipeline.py` ganha testes puros de
  `classify_frost_days` (severo/leve/limite exato) e um teste de
  integração pro alerta de nível leve (`RiskLevel.YELLOW`, mensagem com
  "leve" sem "forte"). Testes existentes de spray-window continuam
  passando sem alteração (novos campos são aditivos).
- A trafegabilidade fica só no frontend por enquanto — se algum dia
  precisar entrar como alerta persistido (ex: aviso de "janela de colheita
  fechando"), a lógica já existe em `web/src/agro.ts` e pode ser portada
  pro backend seguindo o mesmo padrão de `agro_pipeline.py`.
