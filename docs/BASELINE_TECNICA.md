# Baseline técnica — Fase 0 (diagnóstico)

- **Data da análise:** 2026-09-05
- **Branch analisada:** `claude/stormpulse-project-5a5mij` (branch padrão do
  repositório hoje — não existe `main`, ver pendência P2 abaixo)
- **Commit analisado:** `8b60dee` — "Fix: editar cultura/solo de um talhão
  não atualizava ZARC/NDVI"
- **Árvore de trabalho:** limpa no momento da análise (nada não commitado)
- **Backend:** Python 3.14.5 local / **3.12** na imagem de produção (ver
  [ADR-0061](adr/0061-cobertura-de-branch-instavel-entre-versoes-python.md)
  — divergência de versão já conhecida e documentada, não é achado novo)
- **Node:** v24.15.0 / npm 11.12.1
- **ADRs registradas:** 80 (`0001` a `0080`)

Este documento é a fotografia do estado **real** do sistema nesta data —
não o que a documentação diz que existe, mas o que o código, os testes e
os workflows realmente fazem. Serve de referência pra medir progresso nas
próximas fases.

---

## 1. Mapa de módulos

### Backend (`backend/`)

Monólito modular (ADR-0001) + Celery workers (ADR-0002), FastAPI +
SQLAlchemy 2.0 async + asyncpg + GeoAlchemy2/PostGIS (ADR-0003).

- **`app/core/`** — config (`pydantic-settings`, por instância de app, ADR-0030),
  logging estruturado JSON, RLS (`rls.py`), rate limit, criptografia de
  campo (`crypto.py`, ADR-0055), métricas OpenTelemetry, thresholds do
  motor de risco.
- **`app/auth/`, `app/users/`** — JWT + refresh, Google OAuth, RBAC,
  exclusão de conta (LGPD), ciclo de conta (ADR-0059).
- **`app/locations/`** — CRUD de `Location` (+ talhão via
  `parent_location_id`, ADR-0022), `AlertPreference`, PostGIS
  (`ST_DWithin`), agro (spray-window, rainfall, ZARC via ADR-0069, NDVI via
  ADR-0053), relatório semanal/PDF (ADR-0063/0070/0071).
- **`app/storms/`, `app/alerts/`, `app/notifications/`** — células, risco
  materializado, motor de alerta (`app/alerts/engine.py`, idempotente/
  antispam), entrega (Web Push VAPID + Expo push + e-mail via SES,
  ADR-0078).
- **`app/deforestation/`** (ADR-0072) e **soil moisture** (ADR-0073,
  módulo `app/soilmoisture/`) — providers reais (INPE DETER/PRODES via
  WFS, NASA POWER), sem mock em produção.
- **`app/admin/`** — painel de operador de plataforma cross-tenant
  (ADR-0048/0049/0051), auditoria de mutações, status de pipelines.
- **`app/public/`** — endpoints sem login (modo visitante).
- **`engine/`** — motor determinístico puro (detecção, tracking,
  trajetória, risco) — **regra inviolável do projeto**: nenhuma
  classificação de severidade por LLM (ADR-0005); IA (Claude) só resume
  texto de um resultado já calculado (ADR-0060).
- **`workers/`** — 11 ciclos Celery: ingestão/storm, satélite, agro, NDVI,
  desmatamento, ZARC, raios (REDEMET), avisos oficiais, notificações,
  e-mail transacional, resumo de IA.
- **`alembic/`** — baseline com DDL congelado (ADR-0031), ~80 migrações
  hand-written incrementais desde então.

### Web (`web/`) — dashboard admin real

React + Vite + TypeScript + MapLibre. Fala com a API via `VITE_API_URL`.
Login, locais monitorados, talhões com contorno poligonal, mapa
multi-camada (células, satélite IR colorido, raios, projeção de 1h),
painéis agro completos, painel admin, relatório semanal em PDF.

### App raiz (`src/`, `index.html`, `package.json` da raiz) — produto
**diferente**, não confundir com `web/`

Demo pública standalone que consulta o Open-Meteo **direto do navegador**,
sem backend, sem login. É o que o
[`deploy.yml`](../.github/workflows/deploy.yml) publica no GitHub Pages a
cada push. Não faz parte do produto StormPulse real.

### Mobile (`mobile/`) — Expo SDK 57, RN 0.86.2, React 19.2.3

App plano, sem `react-navigation` (navegação por estado em `App.tsx`),
3 abas (Tempestade/Agro/Locais). Sessão via `expo-secure-store`
(ADR-0028, confirmado no código), push real via Expo (ADR-0023).

**Lacunas de paridade confirmadas contra o web** (auditoria desta fase):
ZARC (ADR-0069), NDVI por talhão (ADR-0053), previsão de 1h da célula
(campo `projected_latitude_1h` nem existe em `mobile/src/types.ts`),
direção do vento (`wind_direction_deg`), relatório semanal/PDF, chaves de
API, painel admin, avisos oficiais, desmatamento DETER/PRODES, umidade de
solo NASA POWER, login Google, forgot/reset password, verificação de
e-mail por link, hCaptcha, modo visitante. `mobile/src/agro.ts` e
`storm.ts` são cópias parciais dos módulos web que pararam de acompanhar
features novas (`classifyNdvi`, `haversineDistanceKm`, `bearingDeg`,
`estimateStormEta` ausentes).

### Infraestrutura (`infra/`, `.github/workflows/`)

Produção real desde ADR-0037: EC2 único (`t3.small`), docker-compose,
nginx com TLS Let's Encrypt multi-domínio (`enzova.com.br` +
`stormpulse.enzova.com.br` + `www`, ADR-0079), deploy contínuo com backup
obrigatório + rollback automático de imagem (ADR-0040/0043/0044/0056),
backup periódico do Postgres, alerta de disco cheio (ADR-0067/0068),
Dependabot ativo (pip + npm×3 + GitHub Actions).

**Isso contradiz diretamente o que `ROADMAP.md`/`ARCHITECTURE.md` dizem
hoje** — ver seção 4 (achados P0).

---

## 2. Funcionalidades existentes vs. experimentais

| Categoria | Real / produção | Experimental / aproximado | Mock explícito |
|---|---|---|---|
| Clima atual/previsão | INMET → CPTEC → Open-Meteo (cadeia de fallback real) | — | `WEATHER_PROVIDER=mock` só em dev/teste |
| Células de tempestade | Detecção real por estação | Refletividade **estimada** via Marshall–Palmer (nunca chamada "radar real" no código — confirmado) | mock explícito, `is_mock=True` |
| Trajetória/ETA/projeção 1h | Cálculo geométrico determinístico | Marcado `experimental=True` no modelo | — |
| Risco (`StormRiskEngine`) | Regras documentadas, determinístico | `experimental=True` sempre | — |
| Satélite (GOES-19/TATHU) | Real, opcional (`SATELLITE_ENABLED`) | Sinal precoce, nunca promovido a "confirmado" | — |
| Raios (REDEMET) | Real, opcional (precisa token — hoje **não configurado em produção**, ver P0) | — | — |
| Agro (geada/seca/CAPE/ETA/VPD/GDD/doença) | Real, limiares genéricos não calibrados por cultura | — | — |
| ZARC (janela de plantio) | Real (portarias oficiais) | Cobertura por cultura/região limitada (404 é uma resposta honesta, não bug) | — |
| NDVI | Real (Sentinel-2) | — | — |
| Desmatamento (DETER/PRODES) | Real (INPE WFS) | — | — |
| Umidade de solo | Real (NASA POWER) | — | — |
| Resumo de alerta por IA | Real (Claude) | **Nunca decide severidade** — só reescreve um resultado já calculado (regra inviolável respeitada, confirmado no código) | — |

Nenhum ponto do sistema representa dado estimado/simulado como observação
real sem o marcador `is_mock`/`experimental` correspondente — confirmado
por leitura direta do código nesta fase (não apenas pela documentação).

---

## 3. Duplicação, código obsoleto ou incompleto (achados de auditorias
   desta sessão, verificados por leitura direta de código)

Resumo priorizado — classificação completa em
[ROADMAP_IMPLEMENTACAO.md](ROADMAP_IMPLEMENTACAO.md):

- `AlertPreference` era um controle morto (persistia, nunca era lido) —
  **corrigido nesta sessão**, commit `ffdfc92`.
- Notificação falhada era terminal, sem retry — **corrigido nesta
  sessão**, commit `117de42` (migração `ad53f9776b9b`).
- Bug de staleness no React: editar cultura/solo de um talhão não
  reexecutava o efeito que busca ZARC/NDVI — **corrigido nesta sessão**,
  commit `8b60dee`.
- Pipeline de raios pode duplicar descargas entre ciclos (sem chave de
  dedup) — **não corrigido, P1**.
- CI builda a imagem Docker duas vezes (uma pra escanear/testar, outra
  pra publicar) — o artefato escaneado não é o que vai pra produção —
  **não corrigido, P0**.
- RLS nunca é exercitada em CI (roda como superusuário) e a lista de
  tabelas protegidas no startup check (`app/core/rls.py`) já está
  desatualizada (faltam `ndvi_images`, `deforestation_checks`) —
  **confirmado por leitura direta nesta fase, não corrigido, P0**.
- Backup do Postgres, por padrão, fica no mesmo volume EBS que ele
  deveria proteger (`BACKUP_S3_BUCKET` é opcional e nem documentado no
  `.env.example`) — **não corrigido, P0**.
- Zero monitoramento externo — se a instância EC2 cair, nada avisa
  ninguém — **não corrigido, P0**.
- Duplicação de fetch/lógica agro entre `Dashboard.tsx` e
  `LocationWeatherCard.tsx` (web) — **não corrigido, P2**.
- `mobile/src/agro.ts`/`storm.ts` são forks parciais que pararam de
  acompanhar o web — **não corrigido, P2**.
- Zero teste de componente React no web (`@testing-library/react` nem
  instalado) — **não corrigido, P1**.
- `types.ts` (web) e `types.ts` (mobile) mantidos à mão em paralelo aos
  schemas Pydantic, sem geração automática — risco sistemático de drift,
  já se materializou pelo menos duas vezes nesta sessão — **não
  corrigido, P1**.

Lista completa (17 achados de backend, 8 de frontend web, 8 de infra/CI,
mais os de mobile desta fase) está preservada nas auditorias originais
desta sessão e consolidada com prioridade em `ROADMAP_IMPLEMENTACAO.md`.

---

## 4. Documentação vs. comportamento real — divergências confirmadas (P0)

A última sincronização real de `README.md`/`ARCHITECTURE.md`/`ROADMAP.md`
foi a ADR-0034 (Fase 9 do hardening). Desde então, **46 ADRs** (0035 a
0080) documentam trabalho que os três arquivos-raiz não refletem:

1. **RLS**: `ROADMAP.md` linha 40 e `ARCHITECTURE.md` §5 dizem
   "Row-Level Security... avaliado e **adiado**". Falso hoje — RLS está
   implementada (migração `0b7b9a5dbd11`, ADR-0054) e ativa em produção,
   confirmado por leitura direta de `app/core/rls.py`. A afirmação
   contrária pode levar alguém a reavaliar/reimplementar algo que já
   existe, ou pior, a confiar erroneamente que o isolamento é só de
   aplicação.
2. **Infraestrutura de produção**: `ARCHITECTURE.md` §11 diz
   "**Produção 🔭: ainda não decidida** — nenhum proxy reverso, TLS,
   domínio ou infraestrutura de deploy real definidos". Falso — produção
   real existe desde ADR-0037, com TLS, domínio próprio (`enzova.com.br`,
   ADR-0079), deploy contínuo, backup, rollback (ADR-0040 a 0080).
   `ROADMAP.md` linha 85-88 repete a mesma afirmação stale.
3. **Cookie HttpOnly (Fase 4 do hardening)**: listado como "🟡 Parcial,
   bloqueada por decisão de domínio de produção ainda não tomada" — a
   decisão **foi tomada** (o domínio existe); vale reavaliar se a
   implementação pode ser completada agora.
4. **README.md endpoints**: lista só as rotas das FASES 1–5 — nenhuma
   menção a ZARC, NDVI, desmatamento, umidade de solo, painel admin,
   relatório PDF, avisos oficiais, raios, direção do vento, projeção de
   1h, site institucional.
5. **Modelo de dados** (`ARCHITECTURE.md` §5): não lista
   `NdviReading`/`NdviImage`, `DeforestationCheck`, `ZarcWindow` (se
   materializado), `AlertVerification`, `ApiKey`, `SatelliteImage` já
   citada mas sem as entidades mais novas.
6. **`SECURITY.md`**: tem um `TODO(owner)` explícito e ainda pendente —
   habilitar "Private vulnerability reporting" nas configurações do
   repositório (ação manual do dono, fora do código).
7. **`deploy.yml`**: `TODO(owner)` sobre a branch padrão não se chamar
   `main` ainda.

---

## 5. Verificações executadas (comandos e resultados reais)

Todos os comandos abaixo foram executados nesta análise, contra o commit
`8b60dee`, com Postgres+PostGIS e Redis reais (containers Docker locais).

### Backend

```bash
cd backend
pytest -q --cov=app --cov=workers --cov=engine --cov-fail-under=85
```
**Resultado:** 524 testes, **0 falhas**, cobertura **93,28%** (gate: 85%).

```bash
ruff check . && ruff format --check .
mypy app engine workers tests
```
**Resultado:** ambos limpos (0 erros) — confirmado repetidamente ao longo
desta sessão a cada mudança.

```bash
pip-audit
```
**Resultado:** `No known vulnerabilities found` (o único item listado é o
próprio pacote `stormpulse-backend`, não publicado no PyPI — skip
esperado, não uma vulnerabilidade).

### Web (`web/`)

```bash
cd web
npx tsc --noEmit          # 0 erros
npx vitest run             # 49 testes, 0 falhas (4 arquivos: format, storm, agro, api)
npm run build               # build OK; aviso pré-existente de chunk >500KB no StormMap
                             # (já é lazy-loaded via LazyStormMap.tsx — confirmado nesta sessão,
                             # não é um code-splitting pendente)
npm audit --omit=dev        # 0 vulnerabilidades em produção
npm audit                    # 5 vulnerabilidades, todas dev-only (vitest/vite/esbuild —
                             # exigem dev server exposto, não afetam o bundle publicado):
                             # 1 critical, 1 high, 3 moderate
```

### Mobile (`mobile/`)

```bash
cd mobile
npx tsc --noEmit           # 0 erros
npx jest --ci                # 16 testes, 0 falhas
npm audit --omit=dev         # 13 vulnerabilidades, todas moderate, 0 critical/high —
                              # cadeia de build/prebuild do Expo (@xmldom/xmldom, uuid<11.1.1
                              # via @expo/config-plugins), não afetam o app publicado
```

### App raiz (demo pública)

```bash
npm audit --omit=dev   # 0 vulnerabilidades em produção
npm audit                # 2 vulnerabilidades, dev-only (1 high vite, 1 moderate esbuild)
```

### Docker / CI

`docker compose config --quiet` valida sem erro (parsing dos dois
compose files). O smoke test completo (build das duas variantes de
imagem, Trivy, subida da stack, testes de integração HTTP, drill de
restore de backup) **não foi re-executado localmente nesta fase** — roda
a cada push no job `docker` do CI (~5min, já verificado verde
repetidamente nos últimos commits desta sessão, incluindo o commit
analisado `8b60dee`) e refazê-lo localmente seria redundante com esse
sinal já disponível e recente.

---

## 6. Multitenant e Row-Level Security — estado real

- Isolamento por tenant é feito **em duas camadas**: toda query já filtra
  por `tenant_id` na aplicação (auditado ao longo do projeto), **e**
  Postgres RLS (`ENABLE`+`FORCE ROW LEVEL SECURITY`, migração
  `0b7b9a5dbd11`) nas tabelas com `TenantMixin`.
- `app/core/rls.py::verify_rls_safety` roda no startup e **falha duro em
  produção** (não apenas loga) se o role de runtime for superusuário, tiver
  `BYPASSRLS`, ou for o mesmo role usado pra migração — ou se qualquer
  tabela da lista `_TENANT_SCOPED_TABLES` não tiver a política ativa.
- **Achado confirmado nesta fase**: essa lista (10 tabelas: `users`,
  `locations`, `alerts`, `alert_verifications`, `ndvi_readings`,
  `notifications`, `push_subscriptions`, `user_reports`, `storm_risks`,
  `api_keys`) **não inclui** `ndvi_images` nem `deforestation_checks`,
  que já têm `TenantMixin` e ganharam RLS em migrações posteriores
  (`e884730e20e4`, `b3f7d1a6e2c8`). O startup check é cego pra essas duas
  — se a política delas for removida por engano, nada detecta.
- **CI nunca exercita RLS de verdade**: migrações e testes de integração
  conectam como `stormpulse` (o role de bootstrap, superusuário do
  container) — RLS nunca bloqueia nada nesses testes, então uma política
  quebrada não seria pega antes de produção.
- `alert_preferences` não tem `tenant_id` próprio — depende só do join
  com `locations` na aplicação (não é coberta por RLS diretamente).

---

## 7. Riscos priorizados (P0–P3)

**P0 — corrigir antes de expandir escopo:**
1. RLS nunca testada em CI + lista de tabelas protegidas desatualizada.
2. Backup do Postgres, por padrão, não sai da mesma instância que
   protege.
3. Zero monitoramento externo (queda total da EC2 é invisível).
4. CI escaneia/testa uma imagem Docker e publica outra (rebuild
   separado).
5. Documentação raiz (README/ARCHITECTURE/ROADMAP) afirma coisas falsas
   sobre RLS e infraestrutura de produção — risco de decisão errada por
   quem confiar nela sem checar o código.

**P1 — corrigir no curto prazo:**
6. Pipeline de raios pode duplicar descargas entre ciclos.
7. Zero teste de componente React no web.
8. `types.ts` mantido à mão (web e mobile) sem checagem automática contra
   o schema OpenAPI do backend.
9. Rollback pós-deploy é 100% manual via SSH.
10. `REDEMET_API_KEY` (raios) e `INMET_API_TOKEN` (leituras por estação)
    não configurados em produção — pipelines correspondentes inativos
    (ver ADR-0080; ação pendente do dono do produto, não um bug de
    código).

**P2 — dívida técnica, sem urgência:**
11. Duplicação de fetch/lógica agro entre componentes web.
12. `mobile/agro.ts`/`storm.ts` desatualizados vs. web (ZARC, NDVI,
    projeção 1h, direção do vento ausentes no mobile).
13. Nenhum job de CI tem `timeout-minutes`.
14. Observabilidade instrumentada mas só exporta pro console (sem
    consumidor real).
15. Branch padrão ainda não é `main` (dois `TODO(owner)` pendentes por
    causa disso).

**P3 — cosmético / baixo risco:**
16. 5 vulnerabilidades dev-only no `web/` (vitest/vite/esbuild) e 2 na
    raiz — não afetam produção, resolvem sozinhas com o próximo bump do
    Dependabot.
17. 13 vulnerabilidades moderate no mobile, cadeia de build do Expo, sem
    fix disponível ainda sem `--force`.
18. `SECURITY.md`: habilitar Private Vulnerability Reporting no GitHub
    (ação manual, 1 clique, fora do código).

---

## 8. Pendências que dependem do dono do produto (não código)

- Habilitar "Private vulnerability reporting" no GitHub (`SECURITY.md`).
- Renomear a branch padrão para `main` (dois TODOs no repo esperando
  isso).
- Solicitar `INMET_API_TOKEN` (e-mail já enviado a
  `cadastro.act@inmet.gov.br`, ADR-0080) e `REDEMET_API_KEY` (cadastro
  ainda não feito) — sem eles, radar/raios continuam sem dado novo.
- Decidir se/quando investir em monitoramento externo (ex.: um cron
  simples via GitHub Actions `on: schedule` batendo em `/health`) e em
  backup off-instance (`BACKUP_S3_BUCKET`, já suportado pelo script,
  só não configurado).
