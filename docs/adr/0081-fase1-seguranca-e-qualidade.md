# ADR-0081 — Fase 1 (Segurança e Qualidade): decisões de escopo

- **Status:** Aceito
- **Data:** 2026-09-05

## Contexto

Fase 1 do ciclo de evolução agroclimática (ver
[BASELINE_TECNICA.md](../BASELINE_TECNICA.md) e
[ROADMAP_IMPLEMENTACAO.md](../ROADMAP_IMPLEMENTACAO.md)), com escopo
definido diretamente pelo dono do produto: dependências vulneráveis,
CORS/cookies/tokens/uploads/logs/rate limit, testes de fluxos críticos,
E2E web, teste de contrato front↔API, gate de vulnerabilidade no CI.

Um diagnóstico prévio (auditoria dedicada, arquivos e comandos reais)
mostrou o sistema em bom estado nesses pontos: zero CVE crítico/alto em
produção (backend/web/mobile), CORS sem o erro clássico de wildcard +
credenciais, cookie de refresh já `httponly`/`secure`/`samesite`
corretos, e a maioria dos 8 fluxos críticos já com teste de backend. O
trabalho desta fase corrigiu os achados reais e preencheu as lacunas
confirmadas — não reescreveu nada que já funcionava.

## Decisões

**Numeração:** esta é a "Fase 1" tal como definida pelo dono do produto —
diferente da minha proposta inicial de rascunho (RLS-em-CI, backup
off-instance, monitoramento externo, imagem única no CI), que fica
renumerada como Fase 1-A (dívida técnica P0 remanescente) no
`ROADMAP_IMPLEMENTACAO.md`, a ser retomada como fase própria depois.

**PII em log (`workers/email.py`):** o e-mail do destinatário era logado
em texto claro nas falhas de envio SES. Trocado por um hash de
correlação truncado (SHA-256[:12]) — permite achar a mesma falha nos logs
sem escrever o endereço real.

**Rate limit de auth (`app/auth/router.py`):** `/refresh`, `/logout` e
`/verify-email` ficavam só sob o limite genérico (120/60s) — agora usam o
mesmo `Depends(_auth_rate_limit)` (10/60s) de `/login`/`/register`.

**Upgrade vite 5→6 / vitest 2→3:** 5 vulnerabilidades encontradas eram
todas do **servidor de desenvolvimento** (path traversal, leitura de
arquivo via Vitest UI) — nunca alcançáveis a partir do build de
produção servido pelo nginx. Corrigido por ser só um bump de versão sem
mudança de config, verificado (lint + testes + build) antes e depois.

**E2E (Playwright) com escopo pequeno, não o catálogo inteiro:** 2 specs
— cadastro+login, e cadastro de fazenda+talhão+geração de relatório —
contra uma API real (nenhum mock de API própria; só a Nominatim de
terceiros é interceptada). Desenhar o contorno do talhão no mapa
(canvas WebGL) foi deixado de fora deliberadamente — automatizar cliques
num canvas MapLibre é frágil por natureza, e a validação de
`boundary_geojson` já tem cobertura completa em
`test_integration_locations.py`; o talhão do teste E2E é criado sem
contorno (campo opcional). Ver `web/e2e/README.md`.

**Teste de contrato via `openapi-typescript`, não geração completa nem
Pact:** `web/src/api-schema.generated.ts` é regenerado a partir do
`/openapi.json` real e o CI falha se ficar desatualizado — detector de
drift, não substituição do `types.ts` escrito à mão (migrar
`api.ts`/`types.ts` para consumir o arquivo gerado é trabalho de fase
futura, não desta).

**Gate de vulnerabilidade no CI:** já existia e já bloqueia (pip-audit
sem exceção, `npm audit --omit=dev --audit-level=high` em cada
ecossistema, Trivy `CRITICAL --ignore-unfixed` nas imagens) — nenhuma
mudança necessária, só confirmado e documentado.

## Consequências

- Novo job `e2e` no CI (Postgres/Redis reais, API real, Playwright) —
  aumenta o tempo total de CI; aceito, já que gate a produção.
- `web/src/api-schema.generated.ts` (4300+ linhas) entra no repositório;
  desatualizado, quebra o CI em vez de silenciosamente divergir.
- `backend/.env` local de desenvolvimento para rodar E2E manualmente usa
  `REFRESH_COOKIE_SECURE=false` (documentado em `web/e2e/README.md`) —
  exceção só para `http://localhost`, nunca o padrão de produção.
