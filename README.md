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

## Endpoints (FASES 1–5)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health`, `/ready` | Liveness / readiness |
| POST | `/api/v1/auth/register` | Cadastro (cria tenant pessoal + usuário) |
| POST | `/api/v1/auth/login` | Login → access + refresh token |
| POST | `/api/v1/auth/refresh` | Renovar tokens |
| GET | `/api/v1/users/me` | Perfil autenticado |
| POST/GET | `/api/v1/locations` | Criar / listar locais monitorados |
| GET/PUT/DELETE | `/api/v1/locations/{id}` | Detalhar / atualizar / remover |
| GET | `/api/v1/locations/{id}/risk` | Última avaliação de risco (404 até a FASE 8) |
| GET | `/api/v1/storms` | Células recentes (vazio até a FASE 6) |
| GET | `/api/v1/storms/nearby` | Células próximas via PostGIS `ST_DWithin` |
| GET | `/api/v1/storms/{id}` | Detalhar célula |
| GET | `/api/v1/alerts` | Alertas do usuário |

> Rotas de tempestade retornam resultados **reais** (vazios enquanto o storm
> engine não existe) — nunca dados fictícios. O provider de dados é escolhido
> por `WEATHER_PROVIDER`: `mock` (SIMULADO, marcado explicitamente) ou
> `inmet` (real, FASE 13 — ver [ADR-0006](docs/adr/0006-integracao-real-inmet.md)).

## Provedor meteorológico real (INMET, FASE 13)

Defina `WEATHER_PROVIDER=inmet` no `.env` para usar a API pública do INMET
(estações automáticas) em vez do mock. Não exige token para o que o pipeline
consome hoje (leituras horárias). Limitações documentadas no ADR-0006:
células de tempestade são aproximadas a partir da taxa de chuva (relação de
Marshall–Palmer, não refletividade de radar real), avisos são casados por
estado (UF) e não por polígono exato, e `forecast` ainda retorna vazio
(pendente resolução de geocódigo IBGE). CEMADEN e radar real ficam para uma
fase futura.

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

## Pipeline (workers) e dashboard

Com o Docker de pé (`docker compose up`), os serviços `worker` (Celery) e
`beat` executam o pipeline `provider → engine → risco → alerta → notificação`
a cada 5 minutos. Para rodar **um ciclo sob demanda**:

```bash
docker compose run --rm api python -m workers.run_once
# -> {"frames": 6, "cells": N, "risks": M, "alerts": K}
```

Depois, `GET /api/v1/storms` e `GET /api/v1/locations/{id}/risk` passam a
retornar dados materializados (marcados `is_mock`/`experimental`).

**Dashboard admin** ([`web/`](web/)): `cd web && npm install && npm run dev`
(aponte para a API com `VITE_API_URL`). Login com um usuário registrado.

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
