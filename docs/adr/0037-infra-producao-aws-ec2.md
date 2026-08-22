# ADR-0037 — Infraestrutura de produção: EC2 único, sem domínio ainda

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto**: instância única `t3.small` (2 vCPU,
  2GiB, elegível ao free tier) rodando tudo via `docker compose`; sem
  domínio próprio por enquanto (só IP/URL da AWS); conta AWS já existe,
  CLI ainda não configurado localmente.

## Contexto

O ciclo de hardening técnico (ADR-0026 a 0036) deixou pendente toda a
preparação de infraestrutura de produção real — não por decisão técnica,
mas porque nenhuma decisão de infraestrutura tinha sido tomada ainda (ver
ADR-0029, Fase 4 do hardening, explicitamente bloqueada por isso). Esta
ADR registra as primeiras decisões reais de deploy.

## Decisão

**Topologia**: tudo num único EC2 `t3.small` — Postgres+PostGIS, Redis,
API, worker, beat e nginx, via `docker compose -f docker-compose.yml -f
docker-compose.prod.yml`. Rejeitado (por ora) separar banco/cache em
serviços gerenciados (RDS/ElastiCache) — mais caro, mais complexo de
configurar, e o t3.small comporta a stack inteira com `SATELLITE_ENABLED=false`
(o padrão do projeto).

**Sem domínio, sem TLS por enquanto**: deploy fica em HTTP simples,
acessado pelo IP público do EC2. `ENVIRONMENT=production` continua sendo
usado (ativa a validação que recusa o JWT secret de desenvolvimento) —
seguro mesmo sem TLS, porque o header HSTS só é honrado pelo navegador
sobre uma conexão HTTPS real; sobre HTTP puro ele é simplesmente ignorado
(`app/core/security_headers.py`).

**Artefatos criados**:
- `docker-compose.prod.yml` — override de produção: imagem pré-buildada do
  GHCR (não builda localmente — a variante satélite sozinha usa ~1.9GB,
  inviável na RAM de um t3.small), Postgres/Redis sem porta publicada no
  host, nginx como único ponto de entrada externo, rotação de log em todo
  serviço (`json-file`, 10MB × 3 arquivos — evita que os 30GB de EBS
  free-tier encham só de log).
- `infra/nginx/nginx.conf` — reverse proxy simples; define `X-Forwarded-For`
  como `$remote_addr` (nunca repassa o que o cliente mandou) — é exatamente
  o hop confiável que o rate limiter da Fase 8 foi desenhado pra aceitar
  ([ADR-0033](docs/adr/0033-hardening-fase-8-rate-limit-proxy.md)).
- Rede Docker dedicada (`172.28.0.0/24`) com IP fixo pro nginx
  (`172.28.0.10`) — permite `TRUSTED_PROXY_IPS=172.28.0.10` exato no `.env`
  do servidor, em vez de confiar numa faixa inteira. Nenhum outro processo
  consegue se apresentar como esse IP: só existe dentro dessa rede Docker
  isolada, e IP de origem de uma conexão TCP não é falsificável através de
  uma conexão real estabelecida.
- `infra/backup-postgres.sh` — `pg_dump` + gzip, retenção de 14 dias local.
  Cópia pra fora da instância (S3) deliberadamente **não automatizada**
  aqui — decidir bucket/IAM role é decisão do dono, não algo pra assumir.
- `infra/README.md` — runbook completo: configuração do AWS CLI (o
  usuário roda, nunca credenciais coladas em chat/commitadas), provisionar
  o EC2 (security group só com 22 e 80, nunca 5432/6379 expostos),
  preparar o servidor, configurar `.env` de produção, subir a stack,
  testar restore de backup, rollback (imagem anterior via
  `STORMPULSE_IMAGE`, `alembic downgrade`), e o caminho de upgrade pra TLS
  quando houver domínio.

## Consequências

- **Fase 4 do hardening continua parcial** — mesmo com infra real agora
  decidida, ainda não há domínio, então a topologia same-origin vs.
  cross-site (que determina `SameSite=Lax` vs. `SameSite=None`+CSRF) segue
  indefinida. Documentado como próximo passo natural assim que houver
  domínio.
- Nenhum recurso AWS foi provisionado por este trabalho — só os artefatos
  de configuração. Criar a instância EC2 de fato é uma ação que só o dono
  da conta pode/deve executar (custo real, credenciais reais).
- Backup existe mas só localmente na mesma instância — não sobrevive a
  perda da instância/EBS. Durabilidade fora da instância (S3) fica como
  item futuro.
- Sem TLS, tráfego entre o navegador do usuário e o EC2 não é criptografado
  — aceitável como primeiro passo de validação/staging, não recomendado
  como estado final antes de qualquer uso com dados reais de usuários.
