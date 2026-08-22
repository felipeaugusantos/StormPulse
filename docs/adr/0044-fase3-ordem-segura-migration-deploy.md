# ADR-0044 — Fase 3: ordem segura de migration e serviços no deploy

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

O script de deploy (dentro do job `deploy` do `ci.yml`, ver ADR-0043)
fazia `docker compose ... up -d` **antes** de `alembic upgrade head` —
API e workers subiam com código novo apontando pro schema antigo por uma
janela de tempo real, até a migração terminar. Também rodava a migração
via `exec` dentro do próprio container `api` já servindo tráfego, em vez
de um container isolado.

## Decisão

Sequência completa extraída para `infra/deploy.sh` — versionado,
revisável como qualquer outro script do repositório (mesmo padrão de
`infra/backup-postgres.sh`/`infra/setup-tls.sh`), não mais inline no
YAML do workflow:

1. Registra as imagens `api`/`web` atualmente rodando (`docker inspect
   --format='{{.Config.Image}}'`) — usadas pro rollback, se algo abaixo
   falhar.
2. `docker compose pull` — baixa as imagens imutáveis desta implantação.
3. `docker compose up -d db redis` — só banco e cache, nada de código de
   aplicação ainda.
4. Espera ativamente (`timeout 60s`, checando `docker inspect
   --format='{{.State.Health.Status}}'`) até os dois reportarem
   `healthy`.
5. Backup pré-deploy (`infra/backup-postgres.sh`) — melhor esforço: uma
   falha aqui **não bloqueia** o deploy (proteger contra um backup
   quebrado impedir uma correção urgente), mas fica registrada no log.
6. `docker compose run --rm api alembic upgrade head` — container
   **descartável e isolado**, nunca o container `api` que já está
   atendendo tráfego. `timeout 120s`.
7. Só agora `docker compose up -d api worker beat web` — a aplicação só
   troca de versão depois que o schema já está correto.
8. Espera `/ready` reportar `"status":"ready"` (`timeout 60s`).
9. Smoke test funcional: `/health`, endpoint público
   (`/api/v1/public/storms`), e confirma via `docker compose ps` que
   `worker`/`beat` estão de pé.

**Rollback automático**: `trap rollback ERR` — qualquer falha em
qualquer um dos passos acima (pull, timeout de saúde, migração, `/ready`,
smoke test) aciona `rollback()`: despeja os últimos 200 logs de cada
serviço (visíveis direto no log do GitHub Actions, sem precisar de SSH
manual pra investigar), e — se havia uma imagem anterior registrada —
sobe `api`/`worker`/`beat`/`web` de volta nela. **Nunca** roda `alembic
downgrade` automaticamente — reverter schema é decisão humana deliberada,
não algo pra um script decidir sozinho a essa altura da madrugada.

## Verificação

Testado localmente contra uma stack real (imagens reais do GHCR, não
mocks): primeiro deploy (sem imagem anterior registrada, caminho
"first deploy"), segundo deploy (registra e mantém a imagem anterior
corretamente), e um deploy **forçado a falhar**
(`STORMPULSE_IMAGE=...:tag-que-nao-existe`, fazendo o `pull` falhar) —
confirmado que o rollback disparou, restaurou as imagens anteriores, e a
stack continuou saudável (`/health`/`/ready` respondendo) depois do
"incidente" simulado.

### Bug real encontrado no primeiro deploy contra o servidor de verdade

O primeiro push desta fase **falhou em produção** — não por causa da
lógica do script, mas por uma interação com a Fase de TLS
([ADR-0039](docs/adr/0039-tls-lets-encrypt-nip-io.md)): uma vez com HTTPS
configurado, a porta 80 do servidor passa a **redirecionar tudo pra
HTTPS** (301), exceto o desafio ACME. `curl -fsS http://localhost/ready`
recebia esse 301 como resposta — `-f` só considera falha um status
≥ 400, então `curl` "tinha sucesso" com um corpo HTML de redirecionamento
em vez do JSON esperado, e o `grep -q '"status":"ready"'` nunca
encontrava nada. O laço de espera girava os 60s inteiros sem nunca
detectar prontidão — mas a API estava, na verdade, funcionando
perfeitamente o tempo todo (confirmado pelos próprios logs de tracing do
`api-1`, mostrando requisições reais sendo atendidas com sucesso durante
a "espera").

**O rollback automático funcionou exatamente como desenhado**: restaurou
a imagem anterior (`sha-ec50427`, a da Fase 2), produção nunca ficou fora
do ar, e o log da Action mostrou claramente o que aconteceu.

Corrigido com um helper `curl_local()` que tenta HTTPS primeiro
(`curl -k` — a validação de certificado não importa numa checagem de
prontidão local, feita de dentro do próprio servidor) e cai pra HTTP
simples se a porta 443 não responder (servidor que ainda não rodou
`setup-tls.sh`). Reproduzido o cenário exato localmente (certificado de
teste autoassinado instalado no volume `certbot-etc`, `nginx.conf.active`
trocado pra config HTTPS) antes de confirmar a correção — sem essa
reprodução deliberada, a mesma classe de erro poderia ter passado
despercebida de novo.

## Consequências

- Nunca mais há uma janela onde API/workers novos rodam contra schema
  antigo, nem onde uma migração roda dentro de um container já atendendo
  tráfego real.
- Uma falha de deploy deixa a stack rodando a versão anterior conhecida-boa
  em vez de travada num estado parcialmente atualizado.
- `docker compose logs` de uma falha aparece direto no log da Action —
  não é preciso SSH manual pra descobrir o que quebrou.
- Fora de escopo (deliberado): rollback de schema automático — continua
  exigindo decisão humana explícita (`alembic downgrade` ou restore de
  backup, ambos documentados em `infra/README.md § Rollback`).
