# ADR-0035 — Hardening (Fase 10): frontend e observabilidade

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

Fase original do ciclo de hardening pedia: investigar o chunk de 800KB+ do
MapLibre, code-splitting onde trouxer benefício real, testes mínimos de
frontend, revisão de sourcemaps de produção e métricas operacionais
(duração/falha de ciclo, idade do dado meteorológico, fonte ativa/fallback,
alertas gerados/suprimidos, falhas de notificação, latência de API
externa).

## Descobertas

### Code-splitting do MapLibre — já implementado

`web/src/components/LazyStormMap.tsx` já existe e já usa `React.lazy` +
`Suspense` para adiar o import do MapLibre GL (a dependência mais pesada do
bundle) até o mapa realmente montar — `Dashboard.tsx` e `VisitorView.tsx`
já importam `StormMap` desse wrapper, não direto de `StormMap.tsx`. Essa
mudança tinha sido feita antes desta ADR, sem uma ADR própria. Build atual
(`npm run build`): `index-*.js` (bundle inicial, sem o mapa) 191.80 kB
(gzip 59.15 kB); `StormMap-*.js` (chunk separado, carregado só quando o
mapa aparece) 808.71 kB (gzip 219.65 kB). O aviso de "chunk > 500kB" do
Vite é sobre esse segundo chunk — é esperado e aceitável: MapLibre GL é
uma biblioteca grande por natureza, code-splitting já tira ela do caminho
crítico (tela de login não paga esse custo); reduzir mais exigiria trocar
de biblioteca de mapas, fora de escopo (contradiria a decisão da
[ADR-0004](docs/adr/0004-maplibre-para-mapas.md)).

### Sourcemaps de produção — já seguros, agora explícitos

O `vite.config.ts` do `web/` não sobrescrevia `build.sourcemap` — o
padrão do Vite (`false`) já se aplicava, confirmado inspecionando
`dist/assets/` após `npm run build`: nenhum arquivo `.map` gerado. Tornado
explícito no config (`build: { sourcemap: false }`) para não depender de
um padrão implícito de uma dependência externa continuar sendo o mesmo no
futuro.

## Decisão

### Testes mínimos de frontend (`web/`)

`web/` não tinha nenhuma infraestrutura de teste. Adicionado
[Vitest](https://vitest.dev/) (`vitest` + `jsdom`, `npm test` →
`vitest run`) — 34 testes novos:

- **`api.test.ts`** — cliente HTTP e renovação de sessão: login, senha
  errada não é tratada como sessão expirada, refresh automático em 401 +
  retry, 401s concorrentes compartilham uma única chamada de refresh,
  refresh token inválido limpa a sessão em vez de entrar em loop, 401 sem
  refresh token disponível é repassado imediatamente, corpo de erro não-JSON
  ainda produz um `ApiError` utilizável, resposta 204 resolve para
  `undefined`, logout limpa os dois tokens.
- **`format.test.ts`** — conversão Kelvin→Celsius, classificação de
  intensidade convectiva por temperatura de topo de nuvem, direção
  cardinal (8 pontos, com wrap-around), "há N min/h".
- **`storm.test.ts`** — classificação CAPE (4 níveis REDEMET), distância
  Haversine, bearing, ETA de tempestade (retorna `null` quando a célula
  não tem velocidade/direção ou está se afastando do alvo).
- **`agro.test.ts`** — classificação de dias de geada (severa/leve por
  dois limiares), formatação de dias de geada, sequência de dias secos
  (para no primeiro gap nos dados, nunca assume que um dia ausente foi
  seco).

CI (`ci.yml`, job `web`): `npm test` roda entre `npm ci` e `npm run build`
— job renomeado para "Web admin (typecheck · tests · build)".

**Fora de escopo, decisão explícita**: o app raiz (`src/`, demo Open-Meteo
standalone) e `mobile/` não ganharam testes novos nesta fase — `mobile/`
já tem sua própria suíte (Fase 3 do hardening, ADR-0028); o app raiz é uma
demo, não o produto (ver [ADR-0034](docs/adr/0034-hardening-fase-9-documentacao-licenca-estrutura.md)),
sem lógica própria não-trivial que justifique o investimento agora.

### Métricas operacionais (backend)

Novo `app/core/metrics.py` — mesmo padrão de `app/core/tracing.py`
(exporta pro console por padrão, adicionalmente via OTLP/HTTP quando
`OTEL_EXPORTER_OTLP_ENDPOINT` está configurado; pulado no ambiente
`test`). Instrumentos:

| Métrica | Tipo | O que mede |
|---|---|---|
| `stormpulse.pipeline.cycle_duration` | histograma (s) | Duração de cada ciclo de worker, por `pipeline` (ingestion/satellite/agro/notification/lightning) |
| `stormpulse.pipeline.cycle_failures` | contador | Ciclos que levantaram exceção, por `pipeline` |
| `stormpulse.weather.source_used` | contador | Chamadas ao provedor meteorológico, por `provider` e se foi fallback |
| `stormpulse.weather.data_age` | histograma (s) | Idade do dado no momento em que foi servido/usado |
| `stormpulse.alerts.generated` | contador | Alertas emitidos, por `pipeline` |
| `stormpulse.alerts.suppressed` | contador | Alertas/notificações suprimidos, por motivo |
| `stormpulse.notifications.failures` | contador | Falhas de entrega de notificação |
| `stormpulse.external_api.latency` | histograma (s) | Latência de chamadas a APIs meteorológicas externas, por `provider`+`method` |

**Pontos de instrumentação**:
- `workers/tasks.py` — as 5 tasks Celery (`run_ingestion_cycle_task`,
  `run_satellite_detection_task`, `run_agro_advisory_task`,
  `run_notification_delivery_task`, `run_lightning_detection_task`) agora
  rodam dentro de `track_pipeline_cycle(nome)` (duração + falha) e emitem
  `alerts_generated`/`alerts_suppressed`/`notification_failures` a partir
  dos campos que os sumários já retornavam (nenhum dado novo calculado, só
  exportado).
- `app/weather/fallback.py` — as 5 chamadas de método do
  `FallbackWeatherProvider` foram unificadas num único helper privado
  `_call()` (antes, 5 blocos try/except quase idênticos) que registra
  `weather_source_used` (fonte real usada + se foi fallback) e
  `external_api_latency` uma vez só, em vez de duplicado 5 vezes.
  Comportamento de fallback em si **não mudou** — os 10 testes existentes
  de `test_weather_fallback.py` passam sem alteração.
- `app/locations/router.py` — os dois endpoints que consomem
  `get_current_data` diretamente (`/current`, `/agro/spray-window`)
  registram `weather_data_age` a partir de `CurrentConditions.observed_at`.
- `workers/celery_app.py` — `configure_metrics()` chamado uma vez no
  import do módulo (mesma gate de `otel_enabled`/`environment != "test"`
  do FastAPI), porque o pipeline roda em processos Celery separados, sem
  nenhum `create_app()` — sem isso, os contadores em `workers/tasks.py`
  nunca teriam nenhum `MeterProvider` real por trás.

**Nenhum dado pessoal, token ou conteúdo sensível em nenhuma métrica** —
todo atributo é um nome de pipeline, provedor, método ou motivo de
supressão; nunca um `user_id`, `tenant_id`, e-mail, IP ou token.

**Limitação conhecida, documentada, não resolvida nesta fase**: o pool de
workers do Celery (`prefork`, o padrão) usa `fork()` para criar processos
filhos que efetivamente executam as tasks — o `MeterProvider` (com sua
thread de exportação em background) é criado uma vez no processo pai,
antes do fork, e threads não sobrevivem a `fork()` nos processos filhos.
Isso é uma limitação conhecida do ecossistema OTel+Celery-prefork em
geral, não algo introduzido ou resolvido por esta ADR. Na prática, o
processo `beat` (que nunca executa corpo de task, só agenda) sempre
exporta corretamente; o worker principal também. Métricas de dentro de
uma task individual em um processo filho *podem* não ser exportadas de
forma confiável — mitigação futura (fora de escopo agora): trocar o pool
para `--pool=threads`/`--pool=solo`, ou mover pra um modelo de push por
task via `OTLPMetricExporter` configurado explicitamente per-worker.

## Verificação

Backend: `ruff check`, `ruff format --check`, `mypy` (strict), suíte
completa com Postgres+Redis reais (`ENVIRONMENT=test`, mesma env do CI) —
100% verde, 89.82% de cobertura, `workers/tasks.py` 100% coberto.

Frontend (`web/`): `npx tsc -b` (typecheck, inclui os testes novos),
`npx vitest run` — 34/34 testes verdes, `npm run build` confirma o
chunking existente e a ausência de sourcemaps no `dist/`.

## Consequências

- Nenhuma mudança de comportamento observável para quem já usa o sistema
  — as métricas são só instrumentação adicional; o refactor do
  `FallbackWeatherProvider` preserva exatamente o mesmo comportamento
  (testes existentes intocados).
- A partir de agora, um coletor OTLP configurado (ou o console em dev)
  mostra: quanto tempo cada ciclo de worker leva e com que frequência
  falha, qual fonte meteorológica está realmente respondendo vs. caindo
  para fallback, quão velho é o dado servido, quantos alertas/notificações
  foram gerados vs. suprimidos, e a latência real das APIs externas.
- Fora de escopo: dashboard/visualização dessas métricas (nenhum
  Grafana/Prometheus no `docker-compose.yml` ainda — seguindo o mesmo
  limite já documentado pra tracing na ADR-0007); testes de frontend além
  do mínimo definido acima; resolver a limitação de fork+prefork descrita
  acima.
