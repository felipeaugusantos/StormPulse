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

## 5. Backup do Postgres

`backup-postgres.sh` faz `pg_dump` + gzip, mantém os últimos 14 dias
localmente:

```bash
chmod +x infra/backup-postgres.sh
sudo mkdir -p /var/backups/stormpulse
```

Crontab (`crontab -e`) — todo dia às 3h:

```cron
0 3 * * * cd /home/ubuntu/StormPulse && ./infra/backup-postgres.sh >> /var/log/stormpulse-backup.log 2>&1
```

**Durabilidade fora da instância** (o backup acima ainda está no mesmo
volume EBS — se a instância for perdida, o backup vai junto): copiar o
`.sql.gz` mais recente pra um bucket S3 depois do dump é o próximo passo
natural, deliberadamente não automatizado aqui — decidir bucket/IAM role é
uma escolha sua, não algo pra assumir.

### Testando o restore

Nunca confie num backup que nunca foi restaurado. Num Postgres
descartável (não na instância de produção):

```bash
docker run -d --name restore-test -e POSTGRES_PASSWORD=test -p 55499:5432 postgis/postgis:16-3.4
sleep 5
gunzip -c /var/backups/stormpulse/stormpulse_<TIMESTAMP>.sql.gz | \
  docker exec -i restore-test psql -U postgres
# confirme os dados, depois:
docker rm -f restore-test
```

## 6. Redis — persistência

`redis-server --appendonly yes` já está configurado (AOF —
Append-Only File, grava cada escrita em disco) tanto no compose de dev
quanto no de produção — sobrevive a um restart do container. Não há
backup adicional de Redis: o conteúdo (cache, broker do Celery, rate
limit) é todo recriável, nunca é a fonte de verdade de nada.

## 7. Rollback

**App**: `STORMPULSE_IMAGE=ghcr.io/felipeaugusantos/stormpulse:sha-<commit-anterior>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` —
troca pra uma imagem anterior já publicada (tags disponíveis: ver
[README.md § Opção C](../README.md)).

**Banco**: `alembic downgrade -1` reverte a migração mais recente (testado
migração-a-migração desde a Fase 6, [ADR-0031](../docs/adr/0031-hardening-fase-6-baseline-alembic-ddl-congelado.md))
— ou restaurar de um backup (passo 5), se o rollback de schema sozinho não
bastar.

## 8. Prevenção de múltiplos Celery Beat

Só um `beat` roda (um serviço no compose, uma instância) — múltiplos beats
duplicariam o agendamento (mesmo ciclo rodando 2x). Se algum dia precisar
de alta disponibilidade do beat, use `celery beat` com um lock distribuído
(ex.: `celerybeat-redis`) — não implementado, não necessário numa instância
única.

## Adicionando TLS depois (quando houver domínio)

Sem domínio hoje, o deploy fica em HTTP simples — `ENVIRONMENT=production`
continua seguro mesmo assim (o header HSTS só é honrado pelo navegador
sobre HTTPS de verdade; sobre HTTP ele é simplesmente ignorado). Quando
houver um domínio (ou mesmo sem comprar um, usando um serviço como
[nip.io](https://nip.io) que resolve `<ip-com-hifen>.nip.io` pro próprio
IP, o suficiente pra emitir um certificado Let's Encrypt real):

1. Rodar [certbot](https://certbot.eff.org/) num container separado
   (ou adicioná-lo ao `web/Dockerfile`) pra emitir/renovar o certificado.
2. `listen 443 ssl` em `web/nginx.conf`, redirect 80→443.
3. Decidir a topologia de domínio (mesmo domínio pro `web/` e pra API, ou
   subdomínios diferentes) — isso é exatamente a decisão que faltava pra
   fechar a Fase 4 do hardening
   ([ADR-0029](../docs/adr/0029-hardening-fase-4-cookie-refresh-token-opt-in.md)):
   same-origin permite `SameSite=Lax` sem CSRF token; cross-site exige
   `SameSite=None` + CSRF token obrigatório.
