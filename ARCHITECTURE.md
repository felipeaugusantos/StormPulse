# StormPulse — Arquitetura

> **Status:** FASES 0–9 concluídas (arquitetura, fundação, banco/modelos, auth,
> localizações+PostGIS, mock provider, detecção, tracking+trajetória, risco, alertas).
> Falta a FASE 10 (workers) para materializar/persistir e agendar o pipeline.
> Este documento descreve a visão arquitetural do produto e o estado atual da
> implementação. Seções marcadas com 🔭 descrevem intenção futura ainda **não**
> implementada.

---

## 1. Visão geral

StormPulse é uma plataforma de **monitoramento meteorológico acionável** —
conceitualmente um "Waze de tempestades". Ela transforma dados meteorológicos
brutos (radar, séries temporais, avisos oficiais) em **alertas simples e
acionáveis** por local monitorado pelo usuário.

O princípio central é a **separação entre o motor meteorológico determinístico**
(que decide *se* e *quão severa* é uma tempestade) e a **camada de aplicação**
(que apenas consome resultados já processados e os entrega ao usuário).

> ⚠️ **Regra inviolável:** LLMs **não** classificam severidade meteorológica.
> A classificação é feita por algoritmos, regras documentadas e (futuramente)
> modelos especializados de ML. LLMs poderão, no futuro, apenas *redigir* textos
> de alerta a partir de uma classificação já feita.

---

## 2. Estilo arquitetural

**Monólito modular + workers especializados.**

Rejeitamos microserviços nesta fase (ver ADR-0001). O sistema é um único
código-base Python organizado em módulos de domínio coesos, com processamento
pesado delegado a *workers* assíncronos fora do ciclo de request/response.

```
                 ┌─────────────────────────────────────────────┐
                 │                  Fontes                       │
                 │  MockWeatherProvider (agora) · INMET/INPE 🔭  │
                 └───────────────────────┬─────────────────────┘
                                         │  (pull agendado)
                                         ▼
                 ┌─────────────────────────────────────────────┐
                 │                  WORKERS                      │
                 │  ingestão → detecção → tracking → trajetória  │
                 │           → risco → geração de alertas        │
                 │              (Storm Engine)                   │
                 └───────────────────────┬─────────────────────┘
                                         │  escreve resultados
                          ┌──────────────┴──────────────┐
                          ▼                              ▼
                 ┌─────────────────┐            ┌─────────────────┐
                 │  PostgreSQL     │            │      Redis      │
                 │  + PostGIS      │            │  cache / broker │
                 └────────┬────────┘            └────────┬────────┘
                          │        (somente leitura de           │
                          │         resultados processados)      │
                          ▼                                      ▼
                 ┌─────────────────────────────────────────────┐
                 │                FastAPI (API)                  │
                 │   auth · users · locations · storms · alerts  │
                 └───────────────────────┬─────────────────────┘
                                         │  REST/JSON + FCM 🔭
                          ┌──────────────┴──────────────┐
                          ▼                              ▼
                 ┌─────────────────┐            ┌─────────────────┐
                 │  App (Expo) 🔭  │            │ Web admin 🔭    │
                 └─────────────────┘            └─────────────────┘
```

**Consequência-chave:** a API FastAPI **não** executa processamento
meteorológico pesado no caminho do request. Ela lê resultados já materializados
por workers. Isso mantém a API rápida, previsível e escalável separadamente do
engine.

---

## 3. Estrutura de diretórios

```
stormpulse/
├── backend/
│   ├── app/                    # Camada de aplicação (FastAPI)
│   │   ├── core/               # config, logging, middleware, segurança
│   │   ├── db/                 # engine, sessão, base declarativa
│   │   ├── api/                # routers HTTP (health hoje; domínios adiante)
│   │   ├── auth/          🔭   # FASE 3
│   │   ├── users/         🔭   # FASE 2/3
│   │   ├── locations/     🔭   # FASE 4 (PostGIS)
│   │   ├── storms/        🔭   # FASE 6/7
│   │   ├── radar/         🔭   # FASE 13
│   │   ├── alerts/        🔭   # FASE 9
│   │   ├── notifications/ 🔭   # FASE 9 (FCM)
│   │   └── admin/         🔭   # FASE 11
│   ├── engine/            🔭   # Storm Engine (motor determinístico)
│   │   ├── ingestion/          # WeatherProvider → normalização
│   │   ├── radar/              # processamento de frames
│   │   ├── detection/          # detecção de células
│   │   ├── tracking/           # associação temporal de células
│   │   ├── trajectory/         # deslocamento, direção, ETA
│   │   ├── risk/               # StormRiskEngine
│   │   └── forecasting/        # projeção
│   ├── workers/           🔭   # Tarefas Celery + agendamento (beat)
│   ├── alembic/                # migrations
│   ├── tests/                  # pytest
│   └── pyproject.toml
├── web/                   🔭   # Dashboard admin (React + Vite) — FASE 11
├── mobile/                🔭   # App (React Native + Expo) — FASE 12
├── infra/                      # nginx, configs de deploy
├── docs/
│   └── adr/                    # Architecture Decision Records
├── docker-compose.yml
├── .env.example
├── ARCHITECTURE.md
├── ROADMAP.md
└── README.md
```

> Diretórios marcados 🔭 existem como *placeholders* documentados nesta fase;
> serão preenchidos nas fases indicadas. Não criamos código morto.

---

## 4. Fluxo de dados (pipeline do engine) 🔭

O pipeline será orquestrado por workers, em estágios substituíveis:

1. **Ingestão** — `WeatherProvider.get_radar_frames()` → normaliza para um
   formato interno (`RadarFrame`). Nenhuma fonte fica acoplada ao engine.
2. **Detecção** — identifica `StormCell`s em um frame (refletividade, área).
3. **Tracking** — associa células entre frames consecutivos → `StormTrack`.
4. **Trajetória** — a partir de ≥2 observações, calcula deslocamento, direção,
   velocidade e projeta posição futura.
5. **Risco** — `StormRiskEngine` combina intensidade + distância + trajetória
   → `StormRisk` (rain/wind/hail/lightning + severidade + ETA).
6. **Alertas** — regras de negócio decidem se emitem `Alert` e se notificam,
   com idempotência e antispam.

Cada estágio expõe uma **interface** e uma **implementação inicial simples**,
explicitamente marcada como experimental/MOCK quando aplicável, de modo que
possa ser substituída por métodos melhores (ex.: TITAN-like tracking, redes
neurais) sem reescrever o restante.

---

## 5. Modelo de dados (multitenant) 🔭 (FASE 2)

Entidades planejadas (todas com `tenant_id` para isolamento SaaS futuro):

| Entidade            | Papel                                                  |
|---------------------|--------------------------------------------------------|
| `Tenant`            | Organização / conta SaaS                               |
| `User`              | Usuário (RBAC: ADMIN, USER …)                          |
| `Location`          | Local monitorado (lat/lon + raio + geografia PostGIS)  |
| `AlertPreference`   | Tipos de alerta habilitados por local                  |
| `WeatherSource`     | Fonte meteorológica registrada                         |
| `RadarFrame`        | Frame de radar ingerido                                |
| `StormCell`         | Célula detectada em um instante                        |
| `StormTrack`        | Acompanhamento temporal de uma célula                  |
| `StormObservation`  | Observação pontual (posição/intensidade)               |
| `StormRisk`         | Avaliação de risco materializada                       |
| `Alert`             | Alerta gerado para um usuário/local                    |
| `Notification`      | Entrega (FCM) de um alerta                             |
| `UserReport`        | Relato de crowdsourcing (arquitetura preparada)        |

**Geografia:** `Location.geom` e `StormCell.geometry` usam tipos
`geography(Point/Polygon, 4326)` (PostGIS) para consultas de proximidade
eficientes (`ST_DWithin`).

---

## 6. Camada de aplicação (implementada nesta fase)

- **FastAPI** com OpenAPI nativo.
- **Configuração central** via `pydantic-settings` (12-factor, tudo por env).
- **Logging estruturado (JSON)** com `request_id` e `correlation_id`
  propagados por *middleware* + `contextvars`.
- **Health/Readiness:** `GET /health` (liveness, sem dependências) e
  `GET /ready` (readiness: verifica Postgres e Redis).
- **DB async** (SQLAlchemy 2.0 + `asyncpg`) e **Redis async** — inicializados
  no *lifespan* da aplicação e checados no readiness.

---

## 7. Segurança (roadmap FASE 3/14)

JWT de acesso curto + refresh token, hash de senha com `argon2`/`bcrypt`,
rate limiting, validação de entrada via Pydantic, RBAC, proteção contra SQL
injection (ORM parametrizado) e mass assignment (schemas de entrada explícitos),
segredos somente via variáveis de ambiente. Nada de credenciais no código.

---

## 8. Observabilidade

Logs estruturados em JSON, `request_id`/`correlation_id` em cada log e resposta
(`X-Request-ID`), health e readiness endpoints. Métricas/tracing (OpenTelemetry)
ficam para FASE 14.

---

## 9. Decisões arquiteturais

Registradas como ADRs em [`docs/adr/`](docs/adr/):

- **ADR-0001** — Monólito modular + workers (não microserviços).
- **ADR-0002** — Celery como orquestrador de workers.
- **ADR-0003** — SQLAlchemy async + asyncpg + GeoAlchemy2/PostGIS.
- **ADR-0004** — MapLibre para mapas (não Mapbox por padrão).
- **ADR-0005** — Motor de risco baseado em regras documentadas (sem falsa IA).

---

## 10. Riscos e mitigações

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Fontes reais de radar/aviso indisponíveis ou instáveis | Alto | Camada `WeatherProvider` desacoplada; começar com `MockWeatherProvider` explicitamente marcado; validar integração isoladamente na FASE 13 |
| Falsos positivos/negativos de severidade | Crítico | Regras determinísticas documentadas e versionadas; limiares configuráveis; nunca classificar supercélula só por refletividade; marcar algoritmos experimentais |
| Spam de notificações destrói confiança do usuário | Alto | Motor de alertas com idempotência + regras antispam (só reenvia em mudança relevante) |
| Custo/latência de processamento de radar | Médio | Processamento fora do request (workers); cache Redis de resultados |
| Precisão de ETA/trajetória com poucos frames | Médio | Marcar extrapolação inicial como experimental; exigir ≥2 observações; melhorar método na FASE 7 |
| Acoplamento acidental fonte→engine | Médio | Interface `WeatherProvider`; testes garantindo desacoplamento |
| Escopo excessivo cedo demais (microserviços, k8s, billing) | Médio | YAGNI: monólito modular; roadmap em fases |

---

## 11. Modelo de execução

- **Dev local:** `docker compose up` sobe Postgres+PostGIS, Redis e a API.
  A API roda com `uvicorn --reload`.
- **Testes:** `pytest` no `backend/` (health não exige serviços externos).
- **Workers 🔭:** processo Celery separado + Celery Beat para agendamento
  (ex.: puxar frames a cada N minutos), compartilhando o mesmo código-base.
- **Produção 🔭:** VPS Linux, Nginx como reverse proxy, imagens Docker,
  containers separados para API e workers.

Ver [ROADMAP.md](ROADMAP.md) para o plano de fases.
