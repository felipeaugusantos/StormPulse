# E2E (Playwright) — Fase 1 (Segurança e Qualidade)

Escopo deliberadamente pequeno: 3 testes cobrindo os fluxos mais críticos
ponta-a-ponta contra um backend real (nenhum mock da própria API) —
cadastro, login, cadastro de fazenda, cadastro de talhão e geração de
relatório semanal. Não é o catálogo inteiro de fluxos da aplicação.

Fora de escopo por decisão explícita:

- **Desenho de contorno no mapa** (canvas WebGL do MapLibre) — flaky e caro
  de automatizar de forma confiável; a validação de `boundary_geojson` já
  tem cobertura completa em `backend/tests/test_integration_locations.py`.
  O talhão aqui é criado sem contorno (campo opcional).
- **Busca de cidade real via Nominatim** — interceptada
  (`page.route(...)`) pra não depender de um serviço de terceiros nem do
  limite de 1 req/s dele em CI.

## Rodando localmente

Precisa de uma API real rodando (Postgres+Redis reais, migrações
aplicadas) — os testes fazem requisições HTTP de verdade, não mockam
`fetch`:

```bash
docker compose up -d db redis
cd backend && alembic upgrade head && uvicorn app.main:app --port 8000
```

Em outro terminal:

```bash
cd web
npx playwright install --with-deps chromium   # só na primeira vez
npm run e2e
```

O `playwright.config.ts` já sobe o `vite dev` na porta 5173 automaticamente
(mesma porta do `CORS_ALLOWED_ORIGINS` padrão do backend). Só falta a API.

## Variáveis de ambiente relevantes do backend local

`REFRESH_COOKIE_SECURE=false` é necessário para rodar sobre `http://` (o
padrão de produção/`.env.example` é `true`, correto para HTTPS real —
nunca mude esse padrão, só a config local usada por estes testes).

## Teste de contrato (frontend ↔ API)

`npm run contract:generate` (com a API rodando) regenera
`web/src/api-schema.generated.ts` a partir do `/openapi.json` real do
backend, via `openapi-typescript`. O CI roda o mesmo comando e falha se o
arquivo commitado ficar diferente — sinal de que um endpoint mudou de
forma (campo removido/renomeado, tipo diferente) sem o frontend ter
percebido. `web/src/types.ts` continua escrito à mão por enquanto (não
migrado pra este arquivo gerado) — o gerado aqui é só o detector de drift;
migrar `types.ts` pra consumir `api-schema.generated.ts` diretamente é
trabalho de uma fase futura, não deste.
