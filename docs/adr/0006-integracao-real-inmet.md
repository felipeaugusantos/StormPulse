# ADR-0006 — Integração meteorológica real via INMET (sem CEMADEN/radar nesta fase)

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 13

## Contexto

O `WeatherProvider` (ADR anterior, FASE 5) já isola o storm engine de qualquer
fonte concreta. A FASE 13 pede a primeira fonte real, entre as opções citadas
no ROADMAP: INMET, INPE-CPTEC, CEMADEN, radares regionais.

Levantamento:

- **INMET** publica uma API HTTP pública, **sem autenticação**, para lista de
  estações automáticas (lat/lon/UF) e leituras horárias por estação — dá para
  temperatura, vento, chuva e observação atual. Existe um endpoint tokenizado
  para dados mais granulares que hora em hora, mas o pipeline atual (ciclo de
  5 min sobre frames horários) não precisa dele.
- **CEMADEN** expõe um webservice em JSON, mas o acesso exige
  credenciamento/whitelist prévio — não é self-service, então não há como
  integrar sem uma credencial que ninguém possui ainda.
- **Radar de verdade** (refletividade via mosaico GRIB2/binário de INPE ou
  redes regionais) é um projeto à parte: processamento de imagem/binário fora
  do formato JSON simples, volume de dados maior, sem endpoint público
  trivial. Fica fora desta fase.

## Decisão

`InmetWeatherProvider` (`backend/app/weather/inmet.py`) é a única fonte real
adicionada nesta fase. Duas aproximações são feitas, deliberadamente, para
manter o storm engine funcionando ponta-a-ponta sem fabricar confiança:

1. **Células de tempestade não são refletividade de radar.** São derivadas da
   taxa de chuva (mm/h) de cada estação, convertida em refletividade
   equivalente estimada pela relação de Marshall–Palmer
   (`Z = 200·R^1.6`, `dBZ = 10·log10(Z)`) — uma fórmula meteorológica padrão,
   não um número inventado. `area_km2` fica `None` (não medido).
2. **Avisos são casados por estado (UF)** da estação mais próxima, não por
   polígono/geocódigo municipal exato — o feed oficial do INMET é keyed por
   geocódigo IBGE, que não resolvemos a partir de lat/lon nesta fase.

`get_forecast` retorna uma lista de pontos vazia: a API de previsão do INMET
também exige geocódigo IBGE (cadeia de geocodificação reversa não verificável
sem execução real). Ponto vazio é honesto; inventar pontos não seria.

Toda saída do `InmetWeatherProvider` carrega `Provenance(is_mock=False)` —
são dados reais, ainda que aproximados nos dois pontos acima, documentados em
código e aqui, nunca escondidos (ver ADR-0005).

## Justificativa

- Honestidade acima de completude: preferimos um provider real com escopo
  reduzido e limitações explícitas a um provider "completo" que finja ter
  refletividade de radar ou previsão que não existe.
- `WeatherProvider` permanece a única interface acoplada ao storm engine —
  nenhuma mudança em `engine/`.
- Falhas de rede/estação inexistente levantam
  `WeatherProviderUnavailableError`; o worker deve logar e pular o ciclo, não
  substituir silenciosamente por dados mock sob proveniência "real".

## Consequências

- `WEATHER_PROVIDER=inmet` habilita a fonte real (ver `.env.example`).
- CEMADEN e radar real ficam como trabalho futuro (nova ADR quando houver
  credencial/escopo definidos).
- `get_forecast` vazio é uma lacuna conhecida — não bloqueia a fase, mas deve
  ser revisitado com resolução de geocódigo IBGE.
