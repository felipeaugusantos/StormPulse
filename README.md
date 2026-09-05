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

O MVP ponta-a-ponta está implementado e em produção de desenvolvimento:
cadastro, auth (JWT + Google), locais monitorados com PostGIS, motor de
detecção/tracking/risco, alertas, workers (Celery), dashboard web, app
mobile (Expo), três fontes meteorológicas reais em cadeia de fallback
(INMET → CPTEC → Open-Meteo), observação via satélite (opcional) e sinais
agronômicos. Histórico completo fase a fase em [ROADMAP.md](ROADMAP.md).

Desde então, o projeto está em um **ciclo de hardening técnico**
(segurança, CI/CD, reprodutibilidade, sem mudar nenhuma regra ou modelo
meteorológico) — ver a seção "Ciclo de hardening técnico" do
[ROADMAP.md](ROADMAP.md#ciclo-de-hardening-técnico-em-andamento) pro
status fase a fase e os ADRs correspondentes.

- Backend **FastAPI** com OpenAPI, configuração 12-factor e logging estruturado
  (JSON) com `request_id`/`correlation_id`.
- **Health/Readiness:** `GET /health` (liveness) e `GET /ready` (checa Postgres
  e Redis).
- **DB async** (SQLAlchemy 2.0 + asyncpg + GeoAlchemy2/PostGIS) e **Redis
  async** (cache, broker do Celery, rate limiting).
- **Docker/Compose** com Postgres+PostGIS, Redis, API, worker e beat.
- Suíte de testes do backend com cobertura ≥85% (CI), `ruff` (lint+format)
  e `mypy --strict` verdes.

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
| POST | `/api/v1/auth/google` | Login com Google (ID token) — FASE 15 |
| GET | `/api/v1/locations/{id}/forecast` | Previsão (5 dias reais do INMET + 1 histórico) — FASE 15 |
| GET | `/api/v1/public/storms`, `/public/storms/nearby` | Células recentes, sem login — FASE 15 |
| GET | `/api/v1/public/warnings` | Avisos oficiais ao vivo por ponto, sem login — FASE 15 |
| GET | `/api/v1/satellite`, `/satellite/nearby` | Observações via satélite (GDAL+TATHU) — FASE 16 |
| GET | `/api/v1/public/satellite/watches` | Observações via satélite, sem login — FASE 16 |
| GET | `/api/v1/public/satellite/image`, `.../image.png` | Imagem IR do GOES-19 ao vivo (metadados + PNG), sem login — FASE 18 |
| GET | `/api/v1/locations/{id}/agro/spray-window` | Janela de pulverização (vento + chuva prevista quando disponível) — FASE 19/20 |
| GET | `/api/v1/locations/{id}/agro/rainfall` | Chuva acumulada por dia, janela recente — FASE 19 |
| GET | `/api/v1/locations/{id}/forecast-comparison` | Acurácia acumulada por modelo (ECMWF/GFS/ICON) — Fase 2, [ADR-0082](docs/adr/0082-comparacao-validacao-previsoes.md) |
| GET | `/api/v1/locations/{id}/agro/vegetation` | Série histórica NDVI/NDRE/EVI/NDMI/NDWI, qualidade, anomalia e zonas — Fase 5, [ADR-0083](docs/adr/0083-fase5-satelite-inteligencia-talhao.md) |
| GET | `/api/v1/locations/{id}/agro/vegetation/compare` | Comparação entre aquisições confiáveis — Fase 5 |
| GET | `/api/v1/locations/{id}/agro/vegetation/image.png` | Mapa histórico do índice com metadados de fonte/data/qualidade — Fase 5 |
| GET | `/api/v1/locations/{id}/agro/vegetation/export.csv` | Exportação da série espectral — Fase 5 |

> Rotas de tempestade retornam resultados **reais** (vazios enquanto o storm
> engine não existe) — nunca dados fictícios. O provider de dados é escolhido
> por `WEATHER_PROVIDER`: `mock` (SIMULADO, marcado explicitamente), `inmet`
> (real, FASE 13 — ver [ADR-0006](docs/adr/0006-integracao-real-inmet.md)) ou
> `cptec` (real, FASE 17 — só previsão).

## Provedor meteorológico real (INMET, FASE 13/15)

Defina `WEATHER_PROVIDER=inmet` no `.env` para usar a API pública do INMET
(estações automáticas) em vez do mock. Não exige token para o que o pipeline
consome hoje (leituras horárias). Limitações documentadas no ADR-0006/0008:
células de tempestade são aproximadas a partir da taxa de chuva (relação de
Marshall–Palmer, não refletividade de radar real), avisos são casados por
estado (UF) e não por polígono exato, e a previsão (`GET
/locations/{id}/forecast`) traz **5 dias reais do INMET + 1 dia histórico**
(não 7 — limite confirmado da API pública do INMET) via resolução de
geocódigo IBGE pelo nome da estação mais próxima. CEMADEN e radar real
ficam para uma fase futura.

## Redundância INPE/CPTEC (FASE 17)

O INMET já se mostrou instável em produção (indisponibilidade real da API
pública). Com `WEATHER_PROVIDER=inmet` e `CPTEC_FALLBACK_ENABLED=true`
(padrão), `get_current_data`/`get_forecast` caem automaticamente para o
serviço XML público do INPE/CPTEC quando o INMET falha — sem geocódigo
(aceita lat/lon direto), sem chave. A previsão do CPTEC traz até 6 dias
reais (o endpoint chama-se "7dias" mas devolveu 6 no teste ao vivo — não
arredondado para 7). O CPTEC não tem radar/avisos/condições atuais para
coordenadas arbitrárias, então o ciclo de ingestão (`get_radar_frames`)
continua parado quando o INMET cai — só a previsão e as condições atuais
ganham redundância. Ver [ADR-0011](docs/adr/0011-inpe-cptec-fallback.md).

## Terceira redundância: Open-Meteo (FASE 20)

Além do CPTEC, `WEATHER_PROVIDER=inmet` com `OPEN_METEO_FALLBACK_ENABLED=true`
(padrão) tenta o [Open-Meteo](https://open-meteo.com) por último — agregador
internacional sem chave, gratuito até 10.000 chamadas/dia pra uso não
comercial. É o único dos 3 que dá **previsão numérica real de chuva**
(probabilidade + mm), por isso a janela de pulverização
(`/agro/spray-window`) passou a considerar chuva também, não só vento.
Cadeia completa: INMET → CPTEC → Open-Meteo, cada um só tentado quando o
anterior falha. Ver [ADR-0015](docs/adr/0015-open-meteo-terceiro-fallback.md).

## Login com Google e modo visitante (FASE 15)

- **Login com Google**: defina `GOOGLE_CLIENT_ID` (backend, `.env`) e
  `VITE_GOOGLE_CLIENT_ID` (`web/.env.local`) com o mesmo client ID criado em
  https://console.cloud.google.com/apis/credentials (tipo "Web
  application"). Sem essas variáveis, o botão "Sign in with Google"
  simplesmente não aparece — não é um erro.
- **Modo visitante**: botão "Ver sem login" na tela de login — mostra
  células de tempestade e avisos oficiais via `/api/v1/public/*`, sem
  precisar de conta. Locais monitorados e risco personalizado continuam
  exigindo login.

## Observação via satélite (GOES-19 + TATHU, FASE 16)

Detecta convecção crescendo (nuvem esfriando no topo, via infravermelho do
satélite GOES-19) **antes** de virar chuva confirmada — um sinal precoce,
não uma previsão. **Desligado por padrão** (`SATELLITE_ENABLED=false`) por
causa do custo real de infra (GDAL + ~20-30MB baixados a cada ciclo de
10 min). Para ligar:

```bash
SATELLITE_ENABLED=true docker compose up -d --build
```

O Dockerfile já instala GDAL/TATHU (imagem maior, build mais lento — só
nesse caso). Aparece no dashboard como um novo painel/camada no mapa
("Observações via satélite", roxo) e gera alertas próprios
(`SATELLITE_WATCH_DETECTED`/`DISSIPATED`, nível sempre amarelo — sinal
precoce, não uma tempestade confirmada). Limitações e decisões documentadas
no [ADR-0009](docs/adr/0009-satelite-goes19-tathu.md).

Com `SATELLITE_ENABLED=true`, cada ciclo também renderiza a imagem IR real
(banda 13, escala de cinza invertida — convenção meteorológica padrão) a
partir do mesmo grid já reprojetado para detecção, sem custo extra de
download/GDAL. Aparece como camada no mapa (com toggle para
ligar/desligar), servida sem login em `GET /api/v1/public/satellite/image`
(metadados) e `.../image.png` — só a imagem mais recente é guardada, sem
histórico. Ver [ADR-0013](docs/adr/0013-imagem-satelite-ao-vivo.md).

## Sinais agronômicos (FASE 19)

Ligado por padrão (`AGRO_ENABLED=true`) — reusa chamadas que já existem,
sem custo de infra novo. A cada 6h, cada local monitorado é checado:

- **Geada** (`FROST_WARNING`): mínima prevista ≤ `AGRO_FROST_THRESHOLD_C`
  (padrão 3°C — referência agronômica genérica, não específica por
  cultura).
- **Sequência sem chuva** (`DRY_SPELL_WARNING`): N dias consecutivos sem
  chuva mensurável na estação mais próxima (padrão: 7 dias, limiar
  1mm). Chamado assim, não "veranico" — não temos normais climatológicas
  pra afirmar que é anormal pra época do ano.

Dois endpoints live, sem persistência (mesmo padrão do `/forecast`):
`GET /locations/{id}/agro/spray-window` (janela de pulverização — vento
atual + chuva prevista quando a fonte ativa der previsão numérica, ver
[ADR-0015](docs/adr/0015-open-meteo-terceiro-fallback.md)) e
`GET /locations/{id}/agro/rainfall` (chuva acumulada por dia). Decisões e
limitações documentadas no
[ADR-0014](docs/adr/0014-sinais-agronomicos.md).

## ⚠️ Limitações — leia antes de usar em decisões reais

Resumo consolidado do que já está detalhado nas seções acima e nos ADRs
referenciados — junte tudo aqui porque é a parte que mais importa entender
antes de confiar no sistema:

- **StormPulse não substitui alertas oficiais** (INMET, Defesa Civil,
  CEMADEN). É uma camada de conveniência que agrega e simplifica sinais —
  em qualquer situação de risco real, siga os canais oficiais.
- **Não há radar meteorológico real integrado.** Células de tempestade são
  **aproximadas a partir da taxa de chuva** das estações INMET, convertida
  para refletividade estimada via relação de Marshall–Palmer — não é uma
  medição direta de radar (ver [ADR-0006](docs/adr/0006-integracao-real-inmet.md)).
- **Avisos oficiais são casados por estado (UF)**, não por polígono
  geográfico exato — um aviso pode aparecer para todo o estado mesmo que
  afete só uma região dele.
- **Observação por satélite é um sinal precoce, não uma confirmação.**
  Detecta nuvem esfriando no topo (indicativo de convecção crescendo) via
  infravermelho do GOES-19 — sempre nível amarelo, nunca promovido a
  "tempestade confirmada" só por esse sinal (ver
  [ADR-0009](docs/adr/0009-satelite-goes19-tathu.md)). A imagem IR ao vivo
  no mapa é a imagem real do satélite, mas **não é um produto de radar**.
- **Fontes com fallback em cadeia** (INMET → CPTEC → Open-Meteo) — cada
  uma tem cobertura/granularidade diferentes; a previsão pode variar de
  5-6 dias reais a numérica com probabilidade, dependendo de qual fonte
  respondeu.
- **Dados marcados `is_mock`/`experimental`** na API nunca devem ser
  tratados como reais — a resposta sempre indica explicitamente quando um
  valor vem do provider mock ou de um algoritmo ainda experimental.
- **Sinais agronômicos usam limiares genéricos**, não calibrados por
  cultura específica (ver [ADR-0014](docs/adr/0014-sinais-agronomicos.md)).

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

### Opção C — Imagem publicada (GHCR)

O workflow [`ci.yml`](.github/workflows/ci.yml) (jobs `publish-backend`/
`publish-web`, hardening ADR-0043) builda as imagens e publica no GitHub
Container Registry a cada push em qualquer branch (e em tags `vX.Y.Z`,
quando existirem — nenhuma foi criada ainda) — só depois que todos os
testes passarem para aquele commit. Não requer build local:

```bash
docker pull ghcr.io/felipeaugusantos/stormpulse:latest
docker run --rm -p 8000:8000 \
  -e POSTGRES_HOST=<host> -e POSTGRES_PASSWORD=<senha> \
  -e REDIS_HOST=<host> -e JWT_SECRET_KEY=<segredo-forte> \
  ghcr.io/felipeaugusantos/stormpulse:latest
```

Tags disponíveis: `latest` (empurrado a cada push no branch padrão do
repositório — hoje `claude/stormpulse-project-5a5mij`, ainda não renomeado
para `main`, ver ADR sobre governança), `<nome-do-branch>`, `sha-<curto>` e
`vX.Y.Z` quando uma tag de release existir (nenhuma criada ainda). O mesmo
binário serve API, `worker` e `beat` — só o `command` do container muda
(ver `docker-compose.yml`).

> Build/push local de imagens **não funciona neste ambiente de
> desenvolvimento remoto**: o proxy de rede da sandbox bloqueia o download de
> camadas de qualquer registry de containers (Docker Hub, GHCR, ECR, Quay —
> todos testados, todos 403). Por isso a publicação roda via GitHub Actions,
> que tem acesso de rede irrestrito.

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
pytest                       # unitários (não exigem Postgres/Redis)
ruff check . && ruff format --check .
mypy app engine workers tests
pip-audit                    # vulnerabilidades de dependências (FASE 14)
```

Os testes de health cobrem liveness, readiness (deps ok e falha → 503),
propagação de `X-Request-ID` / `X-Correlation-ID` e o OpenAPI.

**Testes de integração** (`@pytest.mark.integration`, FASE 14) cobrem a
camada HTTP dos routers (auth, locations, storms, ciclo do pipeline) contra
Postgres+PostGIS e Redis reais — são pulados automaticamente se essas
dependências não estiverem acessíveis. Para rodá-los:

```bash
docker compose up -d db redis
cd backend && alembic upgrade head
pytest --cov --cov-report=term-missing   # cobertura mínima exigida no CI: 85%
```

### Observabilidade (OpenTelemetry, FASE 14)

Tracing (FastAPI/SQLAlchemy/httpx) exporta para o console por padrão;
defina `OTEL_EXPORTER_OTLP_ENDPOINT` para exportar também via OTLP/HTTP a um
coletor. Ver [ADR-0007](docs/adr/0007-hardening-v1.md) — não há
Jaeger/Prometheus no `docker-compose.yml` ainda.

### CI (GitHub Actions)

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda a cada
push/PR:

- **backend** — `ruff check`, `ruff format --check`, `mypy` (strict),
  `pip-audit`, migrations e `pytest` (unitários + integração, com
  Postgres+PostGIS e Redis reais como `services`, cobertura mínima 85%).
- **docker** — `docker compose build`, sobe a stack completa
  (Postgres+PostGIS, Redis, API) e faz *smoke test* real dos endpoints
  `/health` e `/ready`.

Assim o build/execução Docker é validado de verdade no CI, sem depender do
ambiente local. Dependências (`pip`/`npm`/GitHub Actions) são atualizadas
automaticamente via [Dependabot](.github/dependabot.yml). Política de
segurança: [SECURITY.md](SECURITY.md).

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

## Estrutura — dois produtos frontend distintos, não confunda

Este repositório tem **dois apps React separados**, com propósitos
diferentes — é fácil confundir os dois porque ambos falam de "tempo":

- **App raiz** (`src/`, `index.html`, `package.json` da raiz, nome
  `stormpulse`) — protótipo standalone que consulta o
  [Open-Meteo](https://open-meteo.com) **diretamente do navegador**, sem
  passar pelo backend FastAPI, sem login, sem locais monitorados
  persistidos. **É este que o [`deploy.yml`](.github/workflows/deploy.yml)
  publica no GitHub Pages** — não é o produto StormPulse completo, é uma
  demo pública sem backend.
- **`web/`** (nome `stormpulse-web`) — o dashboard admin de verdade:
  fala com a API FastAPI (`VITE_API_URL`), tem login, locais monitorados
  persistidos, mapa com camadas de tempestade/satélite/raios, talhões.
  Este é o painel que os usuários reais do StormPulse usam. **Não é
  publicado automaticamente em lugar nenhum ainda** — rode localmente
  (`cd web && npm run dev`) ou faça deploy manual.

```
stormpulse/
├── src/                    # App raiz — demo Open-Meteo standalone,
│                            # publicada no GitHub Pages (ver acima)
├── index.html, package.json (raiz)
│
├── backend/                 # API FastAPI + Storm Engine + workers (produto real)
│   ├── app/
│   │   ├── core/            # config, logging, middleware, segurança, rate limit
│   │   ├── db/               # engine/sessão async, base, redis
│   │   ├── auth/, users/, locations/, storms/, alerts/, notifications/, public/
│   │   └── api/               # routers HTTP, health/ready
│   ├── engine/               # Storm Engine (detecção, tracking, trajetória, risco)
│   ├── workers/               # Celery (worker + beat) — pipeline e notificações
│   ├── alembic/               # migrations (baseline com DDL congelado — ver ADR-0031)
│   ├── tests/                 # pytest
│   ├── Dockerfile              # runtime-base / runtime-satellite — ver ADR-0032
│   └── pyproject.toml
├── web/                      # dashboard admin real (produto StormPulse) — ver acima
├── mobile/                   # app Expo (React Native) — paridade com o web
├── infra/                    # nginx, exemplos de deploy
├── docs/adr/                 # decisões arquiteturais (ADRs)
├── docker-compose.yml
├── .env.example
├── ARCHITECTURE.md
├── ROADMAP.md
└── SECURITY.md
```

---

## Stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy (async) · asyncpg · Alembic ·
PostgreSQL + PostGIS · Redis · Celery (workers, FASE 10) · Docker/Compose ·
React+Vite (web) · React Native+Expo (mobile) · MapLibre · Web Push nativo
do navegador (VAPID, sem FCM/APNs) para o web e Expo Push para o mobile
(notificações).

## Licença

A definir.
