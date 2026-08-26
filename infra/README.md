# Infra — deploy em produção (AWS EC2)

Runbook para subir o StormPulse num único EC2 `t3.small` (2 vCPU, 2GiB —
elegível ao free tier), sem domínio próprio ainda (decisão registrada,
hardening ADR-0037). Tudo num único servidor via `docker compose`:
Postgres+PostGIS, Redis, API, worker, beat e o serviço `web` (dashboard
SPA + nginx como reverse proxy da API, mesma origem — ADR-0038).

> **Antes de tudo**: nenhum comando abaixo cria recursos cobrados na AWS
> automaticamente — cada passo é pra você rodar deliberadamente, revisando
> antes. Nada aqui foi executado por um agente; é um runbook.

## 0. Configurar o AWS CLI (uma vez, na sua máquina)

Isso exige suas credenciais — nunca cole `aws_access_key_id`/
`aws_secret_access_key` num chat ou num arquivo versionado.

```bash
# instalar (se ainda não tiver)
# https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

aws configure
# AWS Access Key ID: <criar em IAM > Users > Security credentials>
# AWS Secret Access Key: <idem>
# Default region: us-east-1 (ou a região mais próxima)
# Default output format: json
```

**Recomendado**: crie um usuário IAM dedicado (não use a conta root) com
permissão só para EC2 (`AmazonEC2FullAccess` é o caminho rápido; um
policy mais restrito é melhor, mas fora de escopo deste runbook).

## 1. Provisionar o EC2

Console AWS ou CLI — exemplo de CLI (ajuste `--key-name` para uma keypair
sua já existente, criada em EC2 → Key Pairs):

```bash
# Security group: só 22 (SSH, idealmente restrito ao seu IP) e 80 (HTTP)
aws ec2 create-security-group \
  --group-name stormpulse-sg \
  --description "StormPulse — SSH + HTTP"

aws ec2 authorize-security-group-ingress \
  --group-name stormpulse-sg --protocol tcp --port 22 --cidr <SEU_IP>/32

aws ec2 authorize-security-group-ingress \
  --group-name stormpulse-sg --protocol tcp --port 80 --cidr 0.0.0.0/0

# Ubuntu 24.04 LTS — confirme o AMI ID atual da sua região em
# https://cloud-images.ubuntu.com/locator/ec2/
aws ec2 run-instances \
  --image-id <AMI_ID_UBUNTU_24_04> \
  --instance-type t3.small \
  --key-name <SUA_KEYPAIR> \
  --security-groups stormpulse-sg \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3}'
```

**Nunca exponha as portas 5432 (Postgres) ou 6379 (Redis) no security
group** — o `docker-compose.prod.yml` já nem publica essas portas no host,
mas o security group é a segunda camada de defesa.

## 2. Preparar o servidor

SSH na instância (`ssh -i sua-chave.pem ubuntu@<IP_PUBLICO>`), depois:

```bash
# Docker + Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# saia e entre de novo no SSH pra o grupo `docker` valer

git clone https://github.com/felipeaugusantos/StormPulse.git
cd StormPulse
```

## 3. Configurar o `.env` de produção

**Nunca use o `.env.example` como está** — ele tem
`JWT_SECRET_KEY=dev-insecure-change-me`, que o próprio backend recusa
rodar em produção (`app/core/config.py`, validador
`_forbid_dev_secret_in_production`).

```bash
cp .env.example .env
```

Edite `.env` e ajuste pelo menos:

```bash
ENVIRONMENT=production
JWT_SECRET_KEY=<gerar: openssl rand -base64 48>
POSTGRES_PASSWORD=<senha forte, não a de dev>
CORS_ALLOWED_ORIGINS=http://<IP_PUBLICO_DO_EC2>   # ou o domínio, quando existir
# Confiar exatamente no nginx deste compose — ver docker-compose.prod.yml
# (IP fixo 172.28.0.10, único ponto de entrada da rede interna do Docker).
TRUSTED_PROXY_IPS=172.28.0.10
```

`SATELLITE_ENABLED`/`API_DOCKER_TARGET` continuam `false`/`runtime-base`
por padrão (recomendado — a variante satélite não cabe confortavelmente
num t3.small, ver [ADR-0032](../docs/adr/0032-hardening-fase-7-docker-reproducivel.md)).

## 4. Subir a stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
```

Verificar:

```bash
curl http://localhost/health
curl http://localhost/ready
```

De fora, `http://<IP_PUBLICO_DO_EC2>/health` deve responder `{"status":"ok",...}`.

### Deploy contínuo (opcional)

Depois desse primeiro deploy manual, o job `deploy` de `.github/workflows/ci.yml`
(hardening [ADR-0040](../docs/adr/0040-deploy-continuo-ec2.md)/[ADR-0043](../docs/adr/0043-fase2-deploy-dependente-do-ci.md))
reimplanta sozinho a cada push cujos testes passaram — via uma chave SSH
dedicada (`~/.ssh/authorized_keys` na instância + secret `EC2_SSH_KEY` no
repositório), nunca a chave pessoal de ninguém. Redeploy manual sob
demanda: aba Actions do GitHub → "Deploy to production (EC2)" → "Run
workflow".

## 5. Backup do Postgres

`backup-postgres.sh` faz `pg_dump` + gzip, mantém os últimos 14 dias
localmente. Desde a hardening ADR-0056, `infra/deploy.sh` **exige** um
backup pré-deploy bem-sucedido antes de rodar qualquer migração — um
`pg_dump` que falha, produz arquivo vazio, ou produz um `.gz` corrompido
(verificado com `gzip -t`) bloqueia o deploy inteiro, não só um aviso.

```bash
chmod +x infra/backup-postgres.sh
sudo mkdir -p /var/backups/stormpulse
```

Crontab (`crontab -e`) — todo dia às 3h:

```cron
0 3 * * * cd /home/ubuntu/StormPulse && ./infra/backup-postgres.sh >> /var/log/stormpulse-backup.log 2>&1
```

Variáveis (todas opcionais, todas com um default de desenvolvimento
seguro):

| Variável | Default | Efeito |
|---|---|---|
| `BACKUP_DIR` | `/var/backups/stormpulse` | Onde os `.sql.gz` ficam localmente. |
| `RETENTION_DAYS` | `14` | Backups locais mais velhos que isso são apagados a cada execução. |
| `BACKUP_S3_BUCKET` | *(vazio, desligado)* | Se definido, copia o `.sql.gz` pro bucket depois do dump local — precisa do `aws` CLI instalado e de credenciais via variável de ambiente/IAM role da instância, nunca uma flag de linha de comando (apareceria em `docker top`/logs de processo). Falha de upload nunca apaga o backup local nem falha o script — só avisa. |
| `ALLOW_DEPLOY_WITHOUT_BACKUP` (lido por `deploy.sh`, não por este script) | `false` | Único jeito de um deploy prosseguir apesar do backup ter falhado — emite um aviso bem visível nos logs e grava uma linha `AUDIT ...` (com timestamp e commit) em `/var/log/stormpulse-deploy-audit.log`. Nunca ligue isso por padrão; é uma válvula de escape explícita pra quando a própria infra de backup está quebrada e uma correção urgente não pode esperar. |

**Durabilidade fora da instância** (o backup local ainda está no mesmo
volume EBS — se a instância for perdida, o backup vai junto): configure
`BACKUP_S3_BUCKET` com um bucket já existente (criação de bucket/IAM role
é uma decisão sua, deliberadamente não automatizada aqui) pra ter uma
cópia off-instance automática a cada backup.

### Testando o restore

Nunca confie num backup que nunca foi restaurado — automatizado no CI
(step "Backup + restore drill" do job `docker`, ver
`.github/workflows/ci.yml`) a cada push, contra um Postgres descartável de
verdade, não simulado. Esse passo tem um retry de boot: o próprio image
`postgis/postgis` tem uma race conhecida em que o script de inicialização
falha com "duplicate key" na primeira tentativa (não relacionado a este
repositório — confirmado reproduzindo o boot isoladamente, falha em torno
de 1 em cada poucas tentativas). Pra rodar manualmente (nunca na instância
de produção):

```bash
docker run -d --name restore-test -e POSTGRES_PASSWORD=test \
  -e POSTGRES_USER=stormpulse -e POSTGRES_DB=stormpulse \
  postgis/postgis:16-3.4
sleep 8
gunzip -c /var/backups/stormpulse/stormpulse_<TIMESTAMP>.sql.gz | \
  docker exec -i restore-test psql -U stormpulse -d stormpulse -v ON_ERROR_STOP=1
# confirme os dados (ex.: SELECT count(*) FROM tenants;), depois:
docker rm -f restore-test
```

## 6. Redis — persistência

`redis-server --appendonly yes` já está configurado (AOF —
Append-Only File, grava cada escrita em disco) tanto no compose de dev
quanto no de produção — sobrevive a um restart do container. Não há
backup adicional de Redis: o conteúdo (cache, broker do Celery, rate
limit) é todo recriável, nunca é a fonte de verdade de nada.

## 7. Rollback

**Automático**: `infra/deploy.sh` (hardening Fase 3,
[ADR-0044](../docs/adr/0044-fase3-ordem-segura-migration-deploy.md);
worker/beat independentes, [ADR-0056](../docs/adr/0056-rollback-worker-backup-obrigatorio.md))
grava a imagem de **cada um** dos quatro serviços (api, web, worker, beat)
antes de mexer em qualquer coisa — worker e beat podem estar em imagens
diferentes da de api (`STORMPULSE_WORKER_IMAGE`, a variante `-satellite`
quando `SATELLITE_ENABLED=true`), então cada um volta pra sua própria
imagem anterior, nunca fica preso na imagem nova de um deploy que falhou.
Se a migração ou o smoke test falharem, o rollback roda sozinho, confere
que a imagem anterior de cada serviço ainda existe localmente antes de
trocar, e **verifica de novo** (`/ready` + `docker compose ps`) que o
estado revertido está saudável antes de declarar sucesso — se o próprio
rollback falhar ou o estado revertido não ficar saudável, o script sai
com uma mensagem bem visível de intervenção manual necessária, em vez de
um "WARNING" fácil de perder no meio do log. Nunca faz `alembic
downgrade` sozinho — isso continua decisão humana, ver abaixo.

Coberto por teste automatizado, sem tocar Docker de verdade
(`infra/tests/test_deploy_rollback.sh` — stub de `docker`/`curl`,
cobrindo o caminho feliz, falha de migração com rollback dos 4 serviços,
imagem anterior ausente, e as duas variações do backup obrigatório
abaixo).

**Manual — app**: `STORMPULSE_IMAGE=ghcr.io/felipeaugusantos/stormpulse:sha-<commit-anterior>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` —
troca pra uma imagem anterior já publicada (tags disponíveis: ver
[README.md § Opção C](../README.md)). Pra reverter `worker`/`beat`
também, exporte `STORMPULSE_WORKER_IMAGE`/inclua-os no mesmo `up -d`.

**Manual — banco**: `alembic downgrade -1` reverte a migração mais recente
(testado migração-a-migração desde a Fase 6, [ADR-0031](../docs/adr/0031-hardening-fase-6-baseline-alembic-ddl-congelado.md))
— ou restaurar de um backup (passo 5), se o rollback de schema sozinho não
bastar. **Migrations nunca são revertidas automaticamente** pelo
`deploy.sh`, nem no caminho de rollback: um `alembic downgrade` errado
pode perder dados de um jeito que um `docker compose up` com a imagem
antiga não consegue desfazer sozinho — essa decisão exige um humano
olhando o que a migração de fato mudou.

### Disco cheio (imagens Docker acumuladas)

Cada deploy publica uma tag imutável nova (`sha-<commit>`) — sem poda,
imagens de deploys antigos se acumulam pra sempre e o disco enche,
quebrando `docker compose pull` (e, pior, o próprio rollback, que também
precisa de espaço pra recriar os containers). Aconteceu de verdade em
produção em 2026-08-26 (ver [ADR-0067](../docs/adr/0067-fix-disco-cheio-deploy.md)).

Desde então, `deploy.sh` poda proativamente as imagens do StormPulse que
não são a que está rodando agora, **antes** de puxar as novas — a cada
deploy, não só depois de um sucesso. Se mesmo assim o disco encher (ex.:
volumes de log, backups do Postgres em `infra/backups/`), verifique
manualmente por SSH:

```bash
df -h /
docker system df
docker images --format "{{.Repository}}:{{.Tag}}  {{.Size}}" | sort
```

`docker image prune -a -f` remove **toda** imagem não referenciada por um
container em execução (mais agressivo que a poda automática do
`deploy.sh`) — seguro de rodar manualmente numa instância dedicada ao
StormPulse, mas nunca num host compartilhado com outros serviços.

### Alerta de disco cheio

`check-disk-space.sh` verifica o uso do disco e manda um e-mail (via SES)
pro operador quando cruza um limite — o incidente acima só foi percebido
lendo log de CI manualmente, nada avisou ninguém de verdade. Roda
independente da stack estar de pé (um disco cheio pode até derrubar os
containers, então o alerta não pode depender deles).

```bash
chmod +x infra/check-disk-space.sh
sudo mkdir -p /var/lib/stormpulse
```

Crontab (`crontab -e`) — a cada 15 minutos:

```cron
*/15 * * * * cd /home/ubuntu/StormPulse && DISK_ALERT_EMAIL="$PLATFORM_ADMIN_EMAIL" SES_FROM_EMAIL="$SES_FROM_EMAIL" ./infra/check-disk-space.sh >> /var/log/stormpulse-disk-alert.log 2>&1
```

Variáveis (todas opcionais, todas com um default seguro):

| Variável | Default | Efeito |
|---|---|---|
| `DISK_CHECK_PATH` | `/` | Qual filesystem checar. |
| `DISK_ALERT_THRESHOLD_PERCENT` | `80` | A partir de quanto % de uso o alerta dispara. |
| `DISK_ALERT_EMAIL` | valor de `PLATFORM_ADMIN_EMAIL` | Destinatário do alerta — mesma pessoa promovida a operador da plataforma, a menos que definido separadamente. |
| `SES_FROM_EMAIL` | *(vazio)* | Remetente já verificado na conta SES — mesma variável que o backend usa pros e-mails transacionais. |
| `AWS_REGION` | `us-east-1` | Região da chamada SES. |
| `DISK_ALERT_STATE_FILE` | `/var/lib/stormpulse/disk-alert.state` | Marca um alerta como "em aberto" — evita reenviar a cada execução do cron enquanto o disco continuar acima do limite, e dispara um e-mail de "normalizado" quando volta a ficar abaixo. |

Sem `DISK_ALERT_EMAIL`/`SES_FROM_EMAIL` configurados, o script nunca
falha — só loga e segue (mesma filosofia do `BACKUP_S3_BUCKET` opcional
acima). Coberto por teste automatizado com `df`/`aws` stubados
(`infra/tests/test_check_disk_space.sh`).

## 8. Prevenção de múltiplos Celery Beat

Só um `beat` roda (um serviço no compose, uma instância) — múltiplos beats
duplicariam o agendamento (mesmo ciclo rodando 2x). Se algum dia precisar
de alta disponibilidade do beat, use `celery beat` com um lock distribuído
(ex.: `celerybeat-redis`) — não implementado, não necessário numa instância
única.

## TLS via Let's Encrypt (sem domínio próprio — [nip.io](https://nip.io))

[nip.io](https://nip.io) resolve `<ip-com-hifens>.nip.io` pro próprio IP —
suficiente pra emitir um certificado Let's Encrypt real sem comprar
domínio. Ver [ADR-0039](../docs/adr/0039-tls-lets-encrypt-nip-io.md) para
os detalhes da implementação (fluxo de 2 fases: HTTP-only pro desafio
ACME, depois HTTPS).

**Bootstrap** (só na primeira vez, antes do primeiro `docker compose up`
com esses arquivos — se a stack já estava rodando sem eles, rode isso e
suba de novo):

```bash
cp infra/tls/nginx-http.conf infra/tls/nginx.conf.active
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Emitir o certificado** (troque pelo seu IP público com hífens no lugar
de pontos, e um e-mail real — o Let's Encrypt manda aviso de expiração
nele):

```bash
chmod +x infra/setup-tls.sh
./infra/setup-tls.sh 100-48-193-126.nip.io voce@example.com
```

Confirme em `https://100-48-193-126.nip.io/health`.

### Renovação do certificado

Certificados do Let's Encrypt duram 90 dias. `infra/renew-tls.sh` roda
`certbot renew` (só renova de fato quando faltam <30 dias) e recarrega o
nginx. Crontab (`crontab -e`) — uma vez por semana já é sobra de margem:

```cron
0 4 * * 0 cd /home/ubuntu/StormPulse && ./infra/renew-tls.sh >> /var/log/stormpulse-tls-renew.log 2>&1
```

### Topologia same-origin já decidida

Com o `web/` e a API na mesma origem (mesmo domínio/IP, mesmo nginx —
[ADR-0038](../docs/adr/0038-dashboard-web-mesma-origem-ec2.md)), a decisão
que faltava pra fechar a Fase 4 do hardening
([ADR-0029](../docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md))
já está resolvida: same-origin permite `SameSite=Lax` sem exigir CSRF
token — não há necessidade de `SameSite=None`. Ativar o cookie HttpOnly de
refresh (`REFRESH_COOKIE_ENABLED=true` no `.env`) agora é seguro nessa
topologia; ainda desligado por padrão, ativar é uma escolha do dono do
produto, não algo automático.
