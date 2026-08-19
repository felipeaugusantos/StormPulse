# ⚡ StormPulse

**Plataforma de monitoramento meteorológico acionável — um "Waze de tempestades".**

StormPulse transforma dados meteorológicos complexos (radar, séries temporais,
avisos) em **alertas simples e acionáveis** por local que o usuário monitora
(casa, trabalho, fazenda, evento…). Não é mais um app de previsão do tempo: o
foco é **chuva forte, tempestade severa, granizo, raios, vento forte e
acompanhamento de células de tempestade**.

> ⚠️ **Princípio inviolável:** a classificação meteorológica é
> **determinística / baseada em modelos especializados** — nunca por LLM.
> LLMs poderão, no futuro, apenas *redigir* textos de alerta a partir de uma
> classificação já feita. Ver [`docs/adr/0005`](docs/adr/0005-risk-engine-baseado-em-regras.md).

---

## Estado atual

Este repositório está nas **FASE 0 (arquitetura)** e **FASE 1 (fundação)**.
As demais fases (banco/modelos, auth, PostGIS, storm engine, alertas, workers,
dashboard, app, integração real) estão planejadas no [ROADMAP.md](ROADMAP.md)
e **ainda não implementadas**.

O que já funciona nesta fase:

- Backend **FastAPI** com OpenAPI, configuração 12-factor e logging estruturado
  (JSON) com `request_id`/`correlation_id`.
- **Health/Readiness:** `GET /health` (liveness) e `GET /ready` (checa Postgres
  e Redis).
- Camadas de **DB async** (SQLAlchemy 2.0 + asyncpg) e **Redis async** prontas.
- **Docker/Compose** com Postgres+PostGIS e Redis.
- **pytest** (9 testes), **ruff** (lint+format) e **mypy strict** verdes.

## Documentação

- [ARCHITECTURE.md](ARCHITECTURE.md) — visão, estilo, estrutura, riscos, execução.
- [ROADMAP.md](ROADMAP.md) — plano de fases e escopo do MVP.
- [docs/adr/](docs/adr/) — decisões arquiteturais (ADRs).

---

## Como executar

### Opção A — Docker (recomendado)

```bash
cp .env.example .env
docker compose up --build
```

- API: <http://localhost:8000>
- Docs (Swagger): <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/health>
- Readiness: <http://localhost:8000/ready>

### Opção B — Local (sem Docker)

Requer Python 3.11+ (a imagem de produção usa 3.12). Postgres+PostGIS e Redis
podem vir só do compose (`docker compose up db redis`).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example .env      # ajuste POSTGRES_HOST/REDIS_HOST=localhost
uvicorn app.main:app --reload
```

---

## Como testar

```bash
cd backend
pytest                       # testes (não exigem Postgres/Redis)
ruff check . && ruff format --check .
mypy app tests
```

Os testes de health cobrem liveness, readiness (deps ok e falha → 503),
propagação de `X-Request-ID` / `X-Correlation-ID` e o OpenAPI.

### CI (GitHub Actions)

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda a cada
push/PR:

- **backend** — `ruff check`, `ruff format --check`, `mypy` (strict) e `pytest`.
- **docker** — `docker compose build`, sobe a stack completa
  (Postgres+PostGIS, Redis, API) e faz *smoke test* real dos endpoints
  `/health` e `/ready`.

Assim o build/execução Docker é validado de verdade no CI, sem depender do
ambiente local.

---

## Como criar migrations (Alembic)

Os **modelos** chegam na FASE 2; o scaffolding do Alembic já está pronto.

```bash
cd backend
# gerar uma migration a partir dos modelos (após FASE 2):
alembic revision --autogenerate -m "descricao"
# aplicar:
alembic upgrade head
```

A URL do banco é injetada a partir das settings (`app/core/config.py`) — não há
credencial no `alembic.ini`.

---

## Estrutura

```
stormpulse/
├── backend/
│   ├── app/
│   │   ├── core/          # config, logging, middleware, contexto
│   │   ├── db/            # engine/sessão async, base, redis
│   │   └── api/           # routers (health/ready)
│   ├── engine/            # Storm Engine (placeholder — FASE 6+)
│   ├── workers/           # Celery (placeholder — FASE 10)
│   ├── alembic/           # migrations
│   ├── tests/             # pytest
│   ├── Dockerfile
│   └── pyproject.toml
├── web/                   # dashboard admin (FASE 11)
├── mobile/                # app Expo (FASE 12)
├── infra/                 # nginx e deploy
├── docs/adr/              # decisões arquiteturais
├── docker-compose.yml
├── .env.example
├── ARCHITECTURE.md
└── ROADMAP.md
```

---

## Stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy (async) · asyncpg · Alembic ·
PostgreSQL + PostGIS · Redis · Celery (workers, FASE 10) · Docker/Compose ·
React+Vite (web) · React Native+Expo (mobile) · MapLibre · Firebase Cloud
Messaging (notificações).

## Licença

A definir.
