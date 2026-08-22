# ADR-0040 — Deploy contínuo pra EC2 via GitHub Actions

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto**: automatizar deploy via SSH a partir do
  GitHub Actions, depois de confrontado explicitamente com o trade-off
  (novo vetor de acesso à infraestrutura via secret no repositório).

## Contexto

Até aqui, toda atualização do servidor EC2 (ADR-0037/0038/0039) era
manual: SSH, `git pull`, `docker compose pull && up -d`. Funcional, mas
cada mudança no código só chegava em produção quando alguém lembrava de
rodar isso.

## Decisão

Novo workflow `.github/workflows/deploy-prod.yml`, disparado por
`workflow_run` depois que `docker-publish.yml` termina com sucesso (nunca
antes — reimplantar antes das imagens novas existirem só reaplicaria as
antigas) — mais `workflow_dispatch` pra redeploy manual sob demanda.

**Chave SSH dedicada** (`stormpulse-deploy-bot`, gerada só pra isso, nunca
a chave pessoal de ninguém) — adicionada como mais uma linha em
`~/.ssh/authorized_keys` na instância (não substitui nenhum acesso
existente), guardada como secret `EC2_SSH_KEY` no repositório. Revogável
independentemente do acesso pessoal do dono, removendo a linha do
`authorized_keys` sem afetar mais nada.

O script remoto (via [`appleboy/ssh-action`](https://github.com/appleboy/ssh-action),
pinado em `v1.2.5`, não numa tag flutuante):

1. `git pull --ff-only` — nunca um merge automático; se o checkout do
   servidor divergiu por algum motivo, falha alto (`set -e`) em vez de
   criar um merge commit sozinho.
2. `docker compose pull` + `up -d` — mesmas imagens que
   `docker-publish.yml` acabou de publicar.
3. `alembic upgrade head` — as migrações deste projeto são desenhadas
   pra rodar sem supervisão (baseline com DDL congelado, testada
   upgrade/downgrade ponta a ponta — [ADR-0031](docs/adr/0031-hardening-fase-6-baseline-alembic-ddl-congelado.md)).
4. `docker image prune -f` — sem isso, layers de imagem antigas se
   acumulam a cada deploy; real no disco de 30GB (free-tier) de um
   t3.small.
5. `curl http://localhost/health` — falha o workflow se a API não
   respondeu depois do restart, em vez de reportar sucesso silenciosamente
   com o serviço fora do ar.

## Consequências

- Toda mudança que passa no CI e chega na branch principal vai pro ar
  sozinha, sem passo manual.
- Novo vetor de acesso à infraestrutura: quem tiver acesso de escrita ao
  repositório (ou a esse secret específico) consegue rodar comandos na
  EC2. Mitigado por ser uma chave dedicada e revogável — não elimina o
  risco, só o isola.
- `alembic upgrade head` automático significa que uma migração ruim vai
  pra produção assim que mergeada — não há gate manual de "revisar antes
  de migrar" além da revisão de código do PR em si. Aceito porque a
  Fase 6 do hardening já construiu e testou exatamente essa garantia
  (migrações idempotentes, upgrade/downgrade verificados).
- Rollback continua manual — ver `infra/README.md § Rollback`
  (`STORMPULSE_IMAGE=...sha-<anterior>` + `alembic downgrade`).
