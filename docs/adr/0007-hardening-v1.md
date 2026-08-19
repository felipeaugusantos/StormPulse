# ADR-0007 — Hardening v1: testes de integração, rate limiting geral, OTel, segurança de dependências

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 14

## Contexto

FASE 14 no ROADMAP.md era só um título ("Testes ampliados, observabilidade
(OTel), rate limiting, segurança"), sem escopo. Levantamento: nenhum teste
pytest exercitava a camada HTTP dos routers (só smoke-tests via curl no CI),
`RateLimiter` só protegia `/auth/*`, zero instrumentação de tracing, sem
scan de vulnerabilidade de dependências, sem headers de segurança.

## Decisão

Escopo v1 enxuto, validado previamente com o usuário:

1. **Headers de segurança** (`SecurityHeadersMiddleware`,
   `backend/app/core/security_headers.py`): `X-Content-Type-Options`,
   `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` sempre;
   `Strict-Transport-Security` só em produção. **Sem CSP** — quebraria o
   Swagger UI em `/docs`.
2. **Rate limiting geral**: um segundo `RateLimiter` (`scope="default"`)
   aplicado uma única vez em `app.include_router(v1_router, ...)`
   (`backend/app/main.py`), cobrindo todos os endpoints versionados sem
   tocar em cada router.
3. **OpenTelemetry**: `backend/app/core/tracing.py` instrumenta FastAPI,
   SQLAlchemy e httpx; exporta para console sempre, e via OTLP/HTTP
   adicionalmente se `OTEL_EXPORTER_OTLP_ENDPOINT` estiver setado. Sem
   Jaeger/Prometheus no compose ainda — plugável depois.
4. **Segurança de dependências**: `.github/dependabot.yml` (pip/npm/
   github-actions) + `pip-audit` bloqueante no CI + `SECURITY.md`.
5. **Testes de integração**: `services` (Postgres+PostGIS, Redis) no job
   `backend` do CI; testes marcados `@pytest.mark.integration` cobrindo
   auth, locations (CRUD + isolamento por tenant) e o ciclo completo do
   pipeline (`run_ingestion_cycle` → `/storms` → `/locations/{id}/risk`).
   Auto-skip via `pytest_collection_modifyitems` quando Postgres/Redis não
   estão acessíveis — quem roda `pytest` local sem Docker continua sem
   precisar de infraestrutura. Cobertura medida em **91%**; piso de CI
   fixado em **85%** (margem, não o número exato medido).

## Duas armadilhas reais encontradas na implementação (documentadas para não se repetirem)

- **Rate limiter de `/auth/*` ignora overrides de `Settings` passados a
  `create_app()`**: `backend/app/auth/router.py` constrói seu
  `RateLimiter` uma vez, no import do módulo, a partir de
  `get_settings()` (cache global do processo) — não da instância de
  `Settings` que os testes passam explicitamente. Corrigir isso direito
  exigiria transformar os routers em fábricas parametrizadas por
  `Settings` (mudança maior, fora do escopo v1). Mitigação adotada: CI e
  execução local de testes de integração setam
  `AUTH_RATE_LIMIT_MAX`/`DEFAULT_RATE_LIMIT_MAX` altos como variável de
  ambiente real do processo (lidas antes do primeiro `get_settings()`),
  já que a suíte de testes roda contra um Redis real e compartilhado. A
  lógica do limiter em si já é testada isoladamente
  (`tests/test_ratelimit.py`) com um Redis falso.
- **`app = create_app()` no fim de `main.py`** (necessário para
  `uvicorn app.main:app`) roda como efeito colateral de qualquer import do
  módulo — inclusive durante a coleta de testes — usando `get_settings()`
  real. Sem `ENVIRONMENT=test` no ambiente, isso liga o OTel de verdade
  (thread de exportação em background) mesmo em testes que nunca chamam
  `create_app()` explicitamente. Mitigação: CI e execução local de testes
  setam `ENVIRONMENT=test` no processo — não é um hack, é literalmente o
  que a variável significa; o gate em `create_app()`
  (`environment != "test"`) já existia para isso.

## Fora do escopo (documentado, não escondido)

- CSP real na API.
- Backend de observabilidade rodando (Jaeger/Prometheus) — só a
  instrumentação e exportação console/OTLP existem.
- Cobertura de `workers/celery_app.py`, `workers/run_once.py`,
  `workers/tasks.py` (0% — entrypoints de processo, testados indiretamente
  pelos smoke-tests do job `docker`, não por unit/integration tests).
- Refatorar routers para fábricas parametrizadas por `Settings` (resolveria
  a primeira armadilha acima "de verdade", mas é uma mudança estrutural
  maior que não se justifica só por esta fase).
