# ADR-0057 — Governança do repositório: branch padrão, CHANGELOG, versionamento, licença

- **Status:** Aceito (parcial — ver "Pendências que exigem ação manual" abaixo)
- **Data:** 2026-08-26

## Contexto

Auditoria de governança do repositório (confirmada via `git`/`gh`, não por
suposição) encontrou:

- O branch padrão remoto **não** é `main` — é
  `claude/stormpulse-project-5a5mij` (`gh api repos/.../StormPulse --jq
  '.default_branch'` confirma). O fluxo de publicação de imagens em
  `ci.yml` (`type=raw,value=latest,enable={{is_default_branch}}`) usa
  exatamente esse branch como fonte da tag `latest`, então o mecanismo
  funciona — só o nome não é o convencional.
- Nenhuma branch protection configurada (`gh api
  repos/.../branches/claude/stormpulse-project-5a5mij/protection` → 404
  "Branch not protected").
- Nenhum `CHANGELOG.md`, nenhuma tag git, nenhuma GitHub Release, nenhum
  `CODEOWNERS`, nenhum `CONTRIBUTING.md`.
- Versionamento já consistente: `0.1.0` idêntico em
  `backend/pyproject.toml`, `web/package.json` e `mobile/package.json` —
  nada para corrigir aí, só formalizar a política (Versionamento
  Semântico) daqui pra frente.
- `LICENSE`: ausente, e o README já documenta isso corretamente como "A
  definir" — não é uma lacuna de documentação, é uma decisão pendente do
  responsável pelo projeto. Este ADR **não** cria uma LICENSE nem escolhe
  uma licença.

## Decisão

1. **CHANGELOG.md** criado (`/CHANGELOG.md`), formato Keep a Changelog,
   mantido a partir de agora a cada mudança notável — sem reconstruir
   retroativamente o histórico das fases 1–34 (isso já existe integralmente
   em `git log`; fabricar um changelog detalhado retroativo seria inventar
   um registro que não foi mantido em tempo real).
2. **Versionamento Semântico** (`MAJOR.MINOR.PATCH`) formalizado como
   política a partir da versão atual (`0.1.0`, já consistente nos três
   `package.json`/`pyproject.toml`) — sem bump nesta ADR.
3. **Branch rename e branch protection**: comandos preparados abaixo, **não
   executados** — mudar o branch padrão do repositório e ativar proteção
   de branch são mudanças de configuração do GitHub fora do escopo do que
   este trabalho pode decidir sozinho (podem afetar deploys em andamento,
   integrações externas, ou preferências do dono do repositório sobre
   nome/fluxo de branches).

## Pendências que exigem ação manual

### Renomear o branch padrão para `main`

```bash
# 1. Renomeia o branch (GitHub redireciona PRs/links automaticamente)
gh api -X POST repos/felipeaugusantos/StormPulse/branches/claude/stormpulse-project-5a5mij/rename \
  -f new_name=main

# 2. Localmente, depois do rename remoto:
git fetch origin
git branch -m claude/stormpulse-project-5a5mij main
git branch -u origin/main main
git remote set-head origin -a
```

Depois do rename, o fluxo de publicação de imagens (`ci.yml`) continua
funcionando sem nenhuma mudança de código — `is_default_branch` passa a
apontar para `main` automaticamente.

### Ativar branch protection no branch padrão

```bash
gh api -X PUT repos/felipeaugusantos/StormPulse/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=Docker build & stack smoke test' \
  -f 'required_status_checks.contexts[]=Root app (typecheck · build · audit)' \
  -f 'required_status_checks.contexts[]=Web admin (typecheck · tests · build)' \
  -f 'required_status_checks.contexts[]=Mobile app (typecheck · tests)' \
  -f 'required_status_checks.contexts[]=Infra scripts (ShellCheck + rollback/backup tests)' \
  -F enforce_admins=true \
  -F required_pull_request_reviews=null \
  -F restrictions=null
```

Ajuste a lista de `contexts` se os nomes dos jobs em `ci.yml` mudarem —
copie o nome exato de `gh run view --json jobs` num run recente.

### Escolha de licença

Não decidido por este trabalho. Opções comuns pra um projeto como este
(SaaS com componente proprietário de dados meteorológicos vs. projeto
aberto) — MIT (permissiva, simples), Apache-2.0 (permissiva, com patente),
ou "todos os direitos reservados" (proprietário, sem LICENSE pública).
Quando decidido, crie `LICENSE` na raiz e atualize a seção "Licença" do
`README.md`.

### CODEOWNERS / CONTRIBUTING.md

Não criados nesta ADR — fazem mais sentido quando o projeto tiver mais de
um mantenedor ativo; documentado aqui como gap conhecido, não como
decisão de não fazer.

## Consequências

- `CHANGELOG.md` existe e será mantido a partir de agora; histórico
  anterior permanece só em `git log`/ADRs, por design.
- O branch padrão, a branch protection, a licença e CODEOWNERS/CONTRIBUTING
  continuam pendentes de decisão/execução do responsável pelo repositório
  — nada disso foi executado automaticamente.
