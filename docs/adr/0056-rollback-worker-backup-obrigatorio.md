# ADR-0056 — Rollback independente de worker/beat + backup obrigatório antes de migrations

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Auditoria de infraestrutura encontrou dois bugs reais em `infra/deploy.sh`,
confirmados contra o código (não só a descrição do pedido):

1. **Rollback incompleto.** O script só gravava/restaurava as imagens de
   `api` e `web`. `worker` tem sua própria variável de imagem
   (`STORMPULSE_WORKER_IMAGE` — a variante `-satellite` com GDAL/TATHU
   quando `SATELLITE_ENABLED=true`, ver ADR-0041) que o rollback nunca
   tocava: se um deploy publicasse um `worker` quebrado e a migração ou o
   smoke test falhassem, o rollback restaurava `api`/`web` corretamente
   mas deixava `worker` (e, por não ser explicitamente revertido também,
   potencialmente `beat`) na imagem nova. Reproduzido ao vivo contra a
   versão anterior do script com um `docker`/`curl` simulados
   (`infra/tests/test_deploy_rollback.sh`): o rollback antigo de fato
   reaplicava `STORMPULSE_WORKER_IMAGE` da variável de ambiente do
   próprio deploy que tinha acabado de falhar, não a imagem anterior.

2. **Backup pré-deploy não bloqueava nada.** O comentário no script era
   literal: "a failed backup must not block a deploy that fixes something
   urgent" — uma falha de `pg_dump` (disco cheio, Postgres não
   respondendo) só emitia um `WARNING` e a migração rodava do mesmo jeito,
   sem nenhuma rede de segurança se a migração corrompesse dados (um
   `alembic downgrade` reverte *schema*, não dados perdidos por um bug na
   própria migração).

## Decisão

### Rollback por serviço

`deploy.sh` agora grava `PREV_API_IMAGE`, `PREV_WEB_IMAGE`,
`PREV_WORKER_IMAGE` e `PREV_BEAT_IMAGE` independentemente (via `docker
inspect --format='{{.Config.Image}}'` de cada container), e o `rollback()`
explicitamente define `STORMPULSE_WORKER_IMAGE` pro valor anterior de
`worker` (nunca deixando-o vazio/herdado do ambiente do deploy que
falhou). Antes de trocar qualquer imagem, valida que todas as quatro
ainda existem localmente (`docker image inspect`) — se alguma sumiu
(prune manual, disco limpo), aborta com uma mensagem bem visível de
intervenção manual em vez de tentar um rollback parcial. Depois de
aplicar o rollback, roda a mesma checagem de `/ready` + `docker compose
ps` que o deploy normal usa — um rollback que "aplicou" mas deixou o
stack não saudável não conta como rollback bem-sucedido, e o script agora
diferencia esse caso (mensagem de falha de rollback) do caso "rollback
funcionou, mas o deploy original falhou" (mensagem de sucesso do
rollback).

### Backup obrigatório

`ALLOW_DEPLOY_WITHOUT_BACKUP` (default `false`) — com backup falhando e
essa variável não sendo exatamente `"true"`, o deploy para antes de rodar
qualquer migração. Com `ALLOW_DEPLOY_WITHOUT_BACKUP=true` explícito, o
deploy prossegue, mas emite um bloco de aviso bem visível nos logs e
grava uma linha `AUDIT ...` (timestamp UTC + SHA do commit) em
`/var/log/stormpulse-deploy-audit.log`.

`backup-postgres.sh` também ganhou verificação real de que o backup é
utilizável, não só "o comando saiu com código 0": dump feito num arquivo
separado (não mais direto num pipe pra `gzip`, que mascarava certos tipos
de falha — testado ao vivo: um `pg_dump` que falha depois do `gzip` já ter
começado a ler ainda produz um `.gz` válido, mas vazio, de 20-e-poucos
bytes, que passaria numa checagem `[ -s arquivo ]` sozinha), confere que o
dump não ficou vazio, comprime, e confere o `.gz` final com `gzip -t`.
Ganhou também suporte opcional (`BACKUP_S3_BUCKET`) pra copiar o backup
pra S3 depois do dump local — desligado por padrão, nunca loga
credenciais (vêm só de variável de ambiente/IAM role da instância).

## Verificação

`infra/tests/test_deploy_rollback.sh` e `infra/tests/test_backup_postgres.sh`
— nenhum toca Docker ou Postgres de verdade; um `docker`/`curl` stub
(controlado por variáveis `STUB_*`) simula cada cenário. Cobre: caminho
feliz sem rollback; falha de migração com rollback correto dos 4
serviços (incluindo a asserção específica que o `worker` volta pra sua
própria imagem anterior, não a nova); imagem anterior ausente (aborta com
mensagem clara); backup falhando bloqueia por padrão; backup falhando com
`ALLOW_DEPLOY_WITHOUT_BACKUP=true` prossegue com aviso+auditoria;
`pg_dump` falhando não deixa arquivo utilizável pra trás; retenção
funciona. Confirmado que o teste do rollback por serviço realmente
detecta a regressão rodando contra a versão anterior do script antes
desta ADR — falha exatamente como esperado (`worker` fica na imagem nova
em vez da antiga). `shellcheck` limpo nos dois scripts de produção e nos
dois de teste (só um aviso informativo pré-existente e sem risco, sobre
expansão de variável dentro de aspas simples usadas de propósito).

## Consequências

- Um deploy com backup quebrado agora **para** por padrão — operador
  precisa decidir explicitamente (`ALLOW_DEPLOY_WITHOUT_BACKUP=true`) se
  quer arriscar, nunca um "continuou sem eu perceber".
- Rollback agora cobre exatamente os quatro serviços que o deploy
  atualiza — nenhum fica silenciosamente numa imagem diferente dos outros
  três depois de uma falha.
- Migrations continuam nunca sendo revertidas automaticamente, em nenhum
  caminho (deploy normal ou rollback) — decisão humana, documentada em
  `infra/README.md § Rollback`.
- Fora de escopo desta ADR: teste de restore automatizado em ambiente
  descartável no CI (ver `infra/README.md § Backup` pro procedimento
  manual atual) e upload S3 real (a variável existe e é testável
  localmente, mas nenhum bucket/IAM role foi provisionado ainda — decisão
  do operador).
