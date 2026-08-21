# ADR-0026 — Hardening (Fase 1): branch principal, CI e auditoria Node

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** Ciclo de hardening técnico solicitado pelo proprietário — dívidas de segurança/CI/CD/docs/operação identificadas numa revisão técnica externa

## Contexto

Revisão técnica apontou várias lacunas de CI/CD. Esta ADR cobre a
primeira fase: branch principal, versões de Actions/Node, e auditoria de
dependências Node — sem tocar em regras meteorológicas, autenticação ou
schema de banco (fases seguintes).

Achado confirmado por inspeção direta (`gh repo view`, `git branch -a`):
o repositório **não tem branch `main`** — a branch padrão real é
`claude/stormpulse-project-5a5mij`. `deploy.yml` (GitHub Pages) e
`docker-publish.yml` (GHCR) escutam só `push: branches: [main]`, então
**nunca disparam** nesse repositório hoje. `ci.yml` já escutava
`branches: ["**"]` + todo PR, então não tinha esse problema.

## Decisão

### Branch principal — sem renomear automaticamente

Renomear a branch padrão é uma ação administrativa do repositório (afeta
todo mundo com o repo clonado, PRs abertos, links salvos) — não é seguro
fazer isso de forma automática dentro deste ciclo de hardening. Em vez
disso: `deploy.yml`/`docker-publish.yml` passam a escutar
`branches: [main, claude/stormpulse-project-5a5mij]` — funciona hoje
(nome real) e continua funcionando sem edição adicional quando/se a
branch padrão for renomeada para `main` no futuro (recomendado, mas
decisão do proprietário). Cada arquivo tem um comentário `TODO(owner)`
explicando isso e o que remover depois da renomeação.

**Passo manual pendente (proprietário):** decidir se/quando renomear
`claude/stormpulse-project-5a5mij` → `main` via GitHub (Settings →
Branches → rename), depois remover o nome antigo da lista `branches:`
nos dois workflows.

### Versões de GitHub Actions e Node

Todas as Actions estavam desatualizadas; confirmado via `gh api
repos/<org>/<repo>/releases/latest` e via os PRs que o próprio Dependabot
já tinha aberto (não mergeados) — usados como referência das versões-alvo
reais, não um chute:

| Action | Antes | Depois |
|---|---|---|
| `actions/checkout` | v4 | v7 |
| `actions/setup-python` | v5 | v7 |
| `actions/setup-node` | v4 | v7 |
| `actions/upload-pages-artifact` | v3 | v5 |
| `actions/deploy-pages` | v4 | v5 |
| `docker/setup-buildx-action` | v3 | v4 |
| `docker/login-action` | v3 | v4 |
| `docker/metadata-action` | v5 | v6 |
| `docker/build-push-action` | v6 | v7 |

Node: `20` → `22` (LTS ativa) nos 3 jobs Node do CI e no `deploy.yml`. Não
foi pra `24` (a versão local de desenvolvimento) porque o Expo SDK 51
(mobile) ainda não tem compatibilidade confirmada com Node 24 — 22 é a
LTS ativa mais alta com suporte maduro em todo o ecossistema atual
(Vite, Expo, Metro).

### Auditoria de dependências Node (raiz, web/, mobile/)

Cada job Node do CI (`root` — novo job, `web`, `mobile`) ganhou dois
passos depois do build/typecheck:

1. `npm audit --omit=dev --audit-level=high` — **bloqueia o CI** se uma
   dependência de **runtime** (produção) tiver vulnerabilidade alta ou
   crítica.
2. `npm audit --audit-level=high || true` (com `if: always()`) —
   relatório **completo** (incluindo devDependencies/ferramentas de
   build), sempre visível no log, mas **nunca derruba o CI** — essas são
   as dependências que o próprio pedido de hardening distingue como "só
   de build", que merecem visibilidade mas não devem travar todo mundo
   por uma vulnerabilidade num CLI que não roda em produção.

`dependabot.yml` não cobria o app da raiz (`/`) — só `/web` e
`/mobile` tinham entrada `npm`. Adicionado.

### Achado que vaza para a Fase 2 (não corrigido aqui)

`npm audit --omit=dev` em `mobile/` retorna **32 vulnerabilidades (1
crítica, 19 altas)** — todas na cadeia de build/CLI do Expo
(`@xmldom/xmldom`, `tar`/`cacache`, `postcss`, `send`, `image-size`,
`fast-xml-parser` via `metro`/`@react-native-community/cli-*`), não no
runtime do app publicado. Isso significa que **o job `mobile` do CI vai
ficar vermelho** (passo 1, blocking) até a Fase 2 (atualização
coordenada de Expo SDK/React Native) resolver essas cadeias — decisão
deliberada: preferir um CI vermelho e honesto a esconder a vulnerabilidade
atrás de `audit-level` frouxo. Ver Fase 2 (próxima) para o plano de
correção real (não `npm audit fix --force`, que quebraria
Expo/React Native de forma isolada e sem coordenação de versões).

`root/` e `web/` não têm nenhuma vulnerabilidade de alta/crítica
(confirmado rodando `npm audit --omit=dev --audit-level=high`
localmente antes deste commit) — os dois novos passos passam limpo
hoje.

## Consequências

- CI (`ci.yml`) ganha um job novo (`root`) — o app público da raiz,
  publicado via GitHub Pages, não tinha nenhuma cobertura de CI até
  agora (nem build, nem typecheck, nem audit).
- `mobile` no CI fica vermelho até a Fase 2 — esperado e documentado,
  não é uma regressão desta mudança, é a mudança tornando visível um
  problema que já existia.
- Nenhuma mudança em código de aplicação (backend/frontend) — só
  workflows e `dependabot.yml`. Backend re-verificado (`ruff`, `mypy`,
  `pytest --cov`) para confirmar que nada foi afetado: 100% verde,
  89.42% de cobertura.
