# ADR-0043 — Fase 2: deploy dependente do CI, SHA imutável

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

`docker-publish.yml` e `deploy-prod.yml` eram workflows separados:
`docker-publish.yml` disparava em todo `push`, **sem checar se o CI
(`ci.yml`) tinha passado** — só precisava buildar, não precisava passar
nos testes. `deploy-prod.yml` disparava via `workflow_run` observando
só a conclusão de `docker-publish.yml`. Resultado real: um commit que
falhasse nos testes mas ainda compilasse chegaria a produção sozinho.
Além disso, o deploy sempre puxava a tag `:latest` — sem garantia de que
o SHA implantado fosse exatamente o SHA que qualquer verificação
observou.

## Decisão

**Consolidado num workflow só** (`ci.yml`) — a opção que o próprio
GitHub Actions torna mais robusta: `needs` só funciona dentro do mesmo
arquivo, então em vez de tentar coordenar 3 arquivos via `workflow_run`
(que exigiria propagar `head_sha` manualmente em cada hop, reintroduzindo
exatamente o tipo de corrida que se queria eliminar), os testes,
publicação e deploy agora são jobs do mesmo workflow, na mesma execução,
compartilhando o mesmo `github.sha` do início ao fim — não há hop
nenhum onde esse SHA poderia divergir.

Grafo de dependência: `backend`/`root`/`web`/`mobile`/`docker` (testes,
inalterados) → `publish-backend`/`publish-web` (`needs:` os cinco jobs de
teste) → `deploy` (`needs: [publish-backend, publish-web]`). Se qualquer
job de teste falhar, `needs` impede que publish/deploy sequer comecem —
sem precisar de lógica condicional adicional, é o comportamento padrão do
GitHub Actions.

**Tags imutáveis**: `docker/metadata-action` já gerava uma tag
`sha-<short>` (nada mudou nisso) — o que mudou é que o job `deploy` agora
**usa exatamente essa tag**, calculada a partir do `github.sha` da própria
execução (`sha-${GITHUB_SHA:0:7}`), em vez de depender do que
`docker-compose.prod.yml` resolvia por padrão (`:latest`, se
`STORMPULSE_IMAGE` não estivesse setado no servidor). `latest` continua
sendo publicado — conveniência pra quem quiser rodar a imagem mais
recente manualmente — mas nunca mais é a fonte de verdade do que o
workflow de deploy realmente implanta.

**Preserva a escolha de satélite do servidor** (ADR-0041): se o `.env` do
servidor já tem `STORMPULSE_WORKER_IMAGE` apontando pra uma tag
`-satellite`, o script troca só o *tag* (pro `sha-<commit>-satellite`
desse deploy), sem desligar o modo satélite escolhido manualmente.

**GitHub Environment `production`**: o job `deploy` agora roda sob
`environment: production` — isso por si só já habilita, na aba
Settings → Environments do repositório, a opção de exigir aprovação
manual antes de qualquer deploy (reviewers obrigatórios). **Não
habilitado por esta ADR** — é uma configuração de repositório que só o
dono deve decidir ativar; o workflow já está pronto pra isso quando
(e se) for ligado.

**`concurrency` em duas camadas**: o grupo de nível de workflow
(`ci-${{ ref }}`) evita que dois pushes na mesma branch rodem o pipeline
inteiro em paralelo — mas com uma diferença importante em relação ao
`cancel-in-progress: true` que existia antes: agora só cancela de fato
em eventos de `pull_request` (onde nunca há deploy, cancelar é seguro e
dá feedback mais rápido). Em `push`, a nova execução **fica na fila**
em vez de cancelar a anterior — um push não pode mais interromper um
deploy que já está em andamento. O job `deploy` ainda ganha seu próprio
grupo dedicado (`production-deploy`, nunca cancela), como segunda camada
de proteção contra deploy concorrente.

## Consequências

- Um commit com teste vermelho nunca mais tem imagem publicada nem chega
  a produção — `needs` garante isso estruturalmente, não por convenção.
- `docker-publish.yml` e `deploy-prod.yml` foram removidos (conteúdo
  incorporado a `ci.yml`) — referências a esses nomes de arquivo em
  documentação anterior (ADR-0037/0038/0040, `infra/README.md`) apontam
  agora pros jobs correspondentes dentro de `ci.yml`.
- O log de qualquer deploy mostra explicitamente qual commit SHA foi
  implantado (`echo "Deploying commit $COMMIT_SHA..."`).
- Nenhuma mudança na Fase 3 (ordem migration→serviços) — o script do
  `deploy` continua com `up -d` antes de `alembic upgrade head`
  nesta ADR; é o assunto da próxima fase, deliberadamente não misturado
  aqui.
