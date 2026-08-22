# StormPulse — Arquitetura

> **Status:** MVP ponta-a-ponta concluído e em produção de desenvolvimento —
> auth, PostGIS, Storm Engine, workers, dashboard web, app mobile, três
> fontes meteorológicas reais em cadeia de fallback (INMET → CPTEC →
> Open-Meteo), observação via satélite (opcional) e sinais agronômicos.
> Histórico completo fase a fase: [ROADMAP.md](ROADMAP.md). O projeto está
> atualmente em um **ciclo de hardening técnico** (segurança, CI/CD,
> reprodutibilidade — ver a seção correspondente do ROADMAP), sem mudar
> nenhuma regra ou modelo meteorológico.
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
                 │  INMET → CPTEC → Open-Meteo (fallback em      │
                 │  cadeia) · MockWeatherProvider (dev/testes)    │
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
                 │ auth · users · locations · storms · alerts ·  │
                 │ satellite · agro · public (visitante)          │
                 └───────────────────────┬─────────────────────┘
                                         │  REST/JSON + Web Push
                          ┌──────────────┴──────────────┐
                          ▼                              ▼
                 ┌─────────────────┐            ┌─────────────────┐
                 │  App (Expo)     │            │ Web admin       │
                 │  mobile/        │            │ web/            │
                 └─────────────────┘            └─────────────────┘
```

> Existe ainda um terceiro frontend, **fora deste diagrama**: um app React
> standalone na raiz do repositório (`src/`) que consulta o Open-Meteo
> direto do navegador, sem passar pela API acima — é uma demo pública
> (publicada no GitHub Pages), não o produto StormPulse. Ver
> [README.md, seção "Estrutura"](README.md).

**Consequência-chave:** a API FastAPI **não** executa processamento
meteorológico pesado no caminho do request. Ela lê resultados já materializados
por workers. Isso mantém a API rápida, previsível e escalável separadamente do
engine.

---

## 3. Estrutura de diretórios

```
stormpulse/
├── src/                         # App raiz — demo Open-Meteo standalone (GitHub Pages)
├── backend/
│   ├── app/                     # Camada de aplicação (FastAPI)
│   │   ├── core/                # config, logging, middleware, segurança, rate limit
│   │   ├── db/                  # engine, sessão, base declarativa, redis
│   │   ├── api/                 # routers HTTP: health/ready
│   │   ├── auth/                # registro, login, Google, refresh, logout
│   │   ├── users/                # perfil, exclusão de conta (LGPD)
│   │   ├── locations/             # CRUD + PostGIS, talhão/sub-local, agro
│   │   ├── storms/                 # células, tracking, detalhe
│   │   ├── alerts/                  # alertas do usuário
│   │   ├── notifications/            # Web Push (VAPID) + Expo push
│   │   └── public/                    # endpoints sem login (modo visitante)
│   ├── engine/                  # Storm Engine (motor determinístico)
│   │   ├── detection/            # detecção de células
│   │   ├── tracking/              # associação temporal de células
│   │   ├── trajectory/             # deslocamento, direção, ETA
│   │   └── risk/                    # StormRiskEngine
│   ├── workers/                 # Celery: pipeline, notificações, satélite, raios
│   ├── alembic/                 # migrations (baseline com DDL congelado — ADR-0031)
│   ├── tests/                   # pytest
│   └── pyproject.toml
├── web/                         # Dashboard admin real (React + Vite) — ver README
├── mobile/                      # App (React Native + Expo) — paridade com web/
├── infra/                       # nginx, configs de deploy
├── docs/
│   └── adr/                     # Architecture Decision Records
├── docker-compose.yml
├── .env.example
├── ARCHITECTURE.md
├── ROADMAP.md
├── README.md
└── SECURITY.md
```

---

## 4. Fluxo de dados (pipeline do engine)

Orquestrado por workers (Celery), em estágios substituíveis:

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

## 5. Modelo de dados (multitenant)

Entidades reais (todas com `tenant_id` para isolamento por tenant — hoje
aplicado em nível de aplicação; Row-Level Security no Postgres foi
avaliado e adiado, ver [ADR-0016](docs/adr/0016-push-real-csp-exclusao-conta.md)):

| Entidade            | Papel                                                  |
|---------------------|--------------------------------------------------------|
| `Tenant`            | Organização / conta                                    |
| `User`              | Usuário (RBAC: ADMIN, USER …)                          |
| `Location`          | Local monitorado (lat/lon + raio + geografia PostGIS); pode ter `parent_location_id` (talhão/sub-local) |
| `AlertPreference`   | Tipos de alerta habilitados por local                  |
| `WeatherSource`     | Fonte meteorológica registrada                         |
| `StormCell`         | Célula detectada em um instante                        |
| `StormTrack`        | Acompanhamento temporal de uma célula                  |
| `StormObservation`  | Observação pontual (posição/intensidade)                |
| `StormRisk`         | Avaliação de risco materializada                        |
| `Alert`             | Alerta gerado para um usuário/local                     |
| `Notification`      | Entrega (Web Push/Expo push) de um alerta                |
| `PushSubscription`  | Assinatura de push (web ou token Expo) de um usuário      |
| `ConvectiveWatch`   | Observação via satélite (convecção detectada, GDES-19)     |
| `SatelliteImage`    | Frame IR do GOES-19 renderizado, ao vivo (sem histórico)    |
| `LightningStrike`   | Raio/descarga detectada (API-REDEMET)                        |
| `UserReport`        | Relato de crowdsourcing (arquitetura preparada, ainda sem UI) |

**Geografia:** `Location.geom` e `StormCell.geometry` usam tipos
`geography(Point/Polygon, 4326)` (PostGIS) para consultas de proximidade
eficientes (`ST_DWithin`).

---

## 6. Camada de aplicação

- **FastAPI** com OpenAPI nativo.
- **Configuração central** via `pydantic-settings` (12-factor, tudo por env)
  — lida por instância de app (`request.app.state.settings`), não por um
  singleton de processo, ver [ADR-0030](docs/adr/0030-hardening-fase-5-configuracao-por-instancia.md).
- **Logging estruturado (JSON)** com `request_id` e `correlation_id`
  propagados por *middleware* + `contextvars`.
- **Health/Readiness:** `GET /health` (liveness, sem dependências) e
  `GET /ready` (readiness: verifica Postgres e Redis).
- **DB async** (SQLAlchemy 2.0 + `asyncpg`) e **Redis async** — inicializados
  no *lifespan* da aplicação e checados no readiness.

---

## 7. Segurança

JWT de acesso curto + refresh token (opcionalmente via cookie HttpOnly,
ver [ADR-0029](docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md)),
hash de senha com Argon2, rate limiting por IP/usuário atrás de política de
proxy confiável (ver [ADR-0033](docs/adr/0033-hardening-fase-8-rate-limit-proxy.md)),
validação de entrada via Pydantic, RBAC, proteção contra SQL injection (ORM
parametrizado) e mass assignment (schemas de entrada explícitos), CORS
restritivo, segredos somente via variáveis de ambiente. Nada de credenciais
no código. Ver [SECURITY.md](SECURITY.md) para o processo de reporte de
vulnerabilidades.

---

## 8. Observabilidade

Logs estruturados em JSON, `request_id`/`correlation_id` em cada log e
resposta (`X-Request-ID`), health e readiness endpoints, tracing
(OpenTelemetry — FastAPI/SQLAlchemy/httpx, exporta pro console por padrão
ou OTLP/HTTP se configurado). Métricas operacionais dedicadas (duração de
ciclo do worker, idade do dado meteorológico ativo, alertas
gerados/suprimidos, falhas de notificação) ainda **não existem** — ver
FASE 10 do ciclo de hardening no [ROADMAP.md](ROADMAP.md).

---

## 9. Decisões arquiteturais

Mais de 30 ADRs registradas em [`docs/adr/`](docs/adr/) — as fundacionais:

- **ADR-0001** — Monólito modular + workers (não microserviços).
- **ADR-0002** — Celery como orquestrador de workers.
- **ADR-0003** — SQLAlchemy async + asyncpg + GeoAlchemy2/PostGIS.
- **ADR-0004** — MapLibre para mapas (não Mapbox por padrão).
- **ADR-0005** — Motor de risco baseado em regras documentadas (sem falsa IA).

Lista completa (fontes reais, satélite, hardening técnico etc.) no
[ROADMAP.md](ROADMAP.md), que referencia a ADR de cada fase.

---

## 10. Riscos e mitigações

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Fontes reais de radar/aviso indisponíveis ou instáveis | Alto | Camada `WeatherProvider` desacoplada; cadeia de fallback INMET → CPTEC → Open-Meteo (ver [ADR-0011](docs/adr/0011-inpe-cptec-fallback.md)/[ADR-0015](docs/adr/0015-open-meteo-terceiro-fallback.md)) |
| Falsos positivos/negativos de severidade | Crítico | Regras determinísticas documentadas e versionadas; limiares configuráveis; nunca classificar supercélula só por refletividade; marcar algoritmos experimentais |
| Spam de notificações destrói confiança do usuário | Alto | Motor de alertas com idempotência + regras antispam (só reenvia em mudança relevante) |
| Custo/latência de processamento de radar | Médio | Processamento fora do request (workers); cache Redis de resultados |
| Precisão de ETA/trajetória com poucos frames | Médio | Marcar extrapolação inicial como experimental; exigir ≥2 observações; melhorar método na FASE 7 |
| Acoplamento acidental fonte→engine | Médio | Interface `WeatherProvider`; testes garantindo desacoplamento |
| Escopo excessivo cedo demais (microserviços, k8s, billing) | Médio | YAGNI: monólito modular; roadmap em fases |

---

## 11. Modelo de execução

- **Dev local:** `docker compose up` sobe Postgres+PostGIS, Redis, API,
  `worker` e `beat`. A API roda com `uvicorn --reload`.
- **Testes:** `pytest` no `backend/` (unitários não exigem serviços
  externos; integração precisa de Postgres+Redis reais, auto-pulados se
  ausentes).
- **Workers:** processos Celery separados (`worker` + `beat`),
  compartilhando o mesmo código-base e a mesma imagem Docker (só o
  `command` muda) — pipeline a cada 5min, notificações, satélite, raios,
  agro (6h).
- **Produção 🔭:** ainda não decidida — nenhum proxy reverso, TLS, domínio
  ou infraestrutura de deploy real definidos até agora. Isso bloqueia
  parte da Fase 4 do ciclo de hardening (cookie de sessão, ver
  [ADR-0029](docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md))
  e toda a preparação de infra (backup, TLS, rotação de segredos) — ver
  [ROADMAP.md](ROADMAP.md).

Ver [ROADMAP.md](ROADMAP.md) para o plano de fases.
