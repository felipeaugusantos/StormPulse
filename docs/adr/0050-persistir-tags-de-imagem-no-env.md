# ADR-0050 — Persistir as tags de imagem do deploy em `.env`

- **Status:** Aceito
- **Data:** 2026-08-23

## Contexto

Incidente real, não hipotético: pra promover a primeira conta a operador
da plataforma (ADR-0048), foi preciso rodar `docker compose up -d api`
manualmente no servidor pra pegar a variável `PLATFORM_ADMIN_EMAIL` nova
do `.env`. O comando funcionou (subiu, ficou `healthy`), mas a API
recém-recriada **voltou a rodar código de meses atrás** — sem nenhuma
rota `/admin/*`, sem `is_platform_admin` em lugar nenhum. Nenhum erro,
nenhum aviso — só um comportamento sutilmente errado.

Causa: `docker-compose.prod.yml` define `image:
${STORMPULSE_IMAGE:-ghcr.io/felipeaugusantos/stormpulse:latest}` — e
como `.env` nunca guardava `STORMPULSE_IMAGE`, um `docker compose up`
manual sem essa variável exportada caía direto no fallback `:latest`.
O pipeline (`.github/workflows/ci.yml`, ADR-0043) sempre exporta
`STORMPULSE_IMAGE=sha-<commit>` inline na sessão SSH — nunca grava no
`.env` do servidor — e a tag `latest` do GHCR nunca é publicada a partir
deste branch (só a partir de `main`, e este projeto ainda desenvolve
direto no branch de trabalho). Resultado: `:latest` nesse registry,
pra este servidor, apontava pra uma imagem antiga de alguma vez no
passado — a API "voltou no tempo" de forma completamente silenciosa.

## Decisão

`infra/deploy.sh` agora grava `STORMPULSE_IMAGE`/`STORMPULSE_WEB_IMAGE`/
`STORMPULSE_WORKER_IMAGE` (as que estiverem definidas) no `.env` do
servidor, ao final de todo deploy bem-sucedido — depois de todos os
health checks e do smoke test, depois do `trap - ERR` (uma falha que
aciona rollback nunca persiste a tag da imagem que falhou). Update
in-place se a chave já existe (`sed`), append se não existe.

Consequência prática: a partir de agora, `.env` sempre reflete a última
imagem realmente publicada e validada. Um `docker compose up -d api`
manual, mesmo **sem** `STORMPULSE_IMAGE` exportado na sessão, resolve
pro valor gravado em `.env` — não mais pro `:latest` hardcoded do
compose, que nunca correspondeu a nada real neste branch.

## Fora de escopo

- Publicar `latest` a partir deste branch — misturaria "última imagem
  publicada por qualquer branch" com "última validada pra produção",
  exatamente a confusão que este ADR está corrigindo, só que ao
  contrário.
- Bloquear/avisar num `docker compose up` manual sem `STORMPULSE_IMAGE`
  — desnecessário agora que o fallback do `.env` já é seguro por
  padrão.

## Verificação

- Simulado localmente: `.env` de exemplo com uma chave já presente
  (atualiza in-place, valor antigo substituído) e uma ausente
  (adicionada no fim) — confirmado que uma segunda chamada com um valor
  diferente atualiza corretamente sem duplicar a linha, e que uma
  variável vazia (`STORMPULSE_WORKER_IMAGE` quando não setada) não gera
  entrada nenhuma.
- `bash -n infra/deploy.sh` — sintaxe válida.
- Corrigido meia hora depois do incidente acontecer de verdade: rodado
  manualmente com `STORMPULSE_IMAGE=ghcr.io/felipeaugusantos/stormpulse:sha-cd8f316`
  explícito pra restaurar a API à versão correta antes desta correção
  existir — confirmado que essa foi a causa raiz, e não outra coisa.

## Consequências

- Deploys futuros (automáticos ou manuais) ficam protegidos contra essa
  classe específica de regressão silenciosa.
- `.env` do servidor passa a carregar um pouco mais de estado
  operacional (as tags do último deploy) — mesma filosofia de
  `infra/tls/nginx.conf.active` (ADR-0046): estado gerado, git-ignorado,
  específico deste servidor, nunca versionado no repositório.
