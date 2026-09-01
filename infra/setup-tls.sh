#!/usr/bin/env bash
# StormPulse — configuracao unica de TLS via Let's Encrypt (metodo webroot).
#
# Uso: ./infra/setup-tls.sh <dominio-stormpulse> <email> [dominio-enzova...]
# Exemplo (sem dominio proprio, usando nip.io, um host so):
#   ./infra/setup-tls.sh 100-48-193-126.nip.io voce@example.com
# Exemplo (dominio proprio, StormPulse num subdominio + site institucional
# no apex/www, um unico certificado multi-SAN cobrindo os 3 hosts):
#   ./infra/setup-tls.sh stormpulse.enzova.com.br voce@enzova.com.br \
#     enzova.com.br www.enzova.com.br
#
# O primeiro dominio (obrigatorio) e sempre o host da SPA/API do
# StormPulse — tambem e o nome usado pelo certbot para o diretorio do
# certificado (/etc/letsencrypt/live/<primeiro-dominio>/). Dominios
# extras (opcionais) sao adicionados ao mesmo certificado via -d
# repetido e servidos pelo bloco institucional estatico (ADR-0079) — sem
# eles, esse bloco simplesmente nao tem host nenhum apontando pra ele,
# o que e inofensivo.
#
# Pre-requisito: a stack ja deve estar rodando com
# docker-compose.prod.yml (ver infra/README.md) e a porta 80 acessivel
# publicamente em todos os dominios informados — o Let's Encrypt precisa
# alcancar cada um deles pra validar o desafio ACME.

set -euo pipefail

STORMPULSE_DOMAIN="${1:?Uso: $0 <dominio-stormpulse> <email> [dominio-enzova...]}"
EMAIL="${2:?Uso: $0 <dominio-stormpulse> <email> [dominio-enzova...]}"
shift 2
ENZOVA_DOMAINS=("$@")
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

CERTBOT_DOMAIN_ARGS=(-d "$STORMPULSE_DOMAIN")
for d in "${ENZOVA_DOMAINS[@]:-}"; do
  [ -n "$d" ] && CERTBOT_DOMAIN_ARGS+=(-d "$d")
done
# nginx's `server_name` can't be an empty string — quando nenhum domínio
# institucional é passado (ex.: o fluxo antigo, um único host via
# nip.io), usa um host do TLD reservado .invalid (RFC 2606) que nunca
# bate com tráfego real, em vez de deixar o server{} sem server_name.
ENZOVA_SERVER_NAMES="${ENZOVA_DOMAINS[*]:-enzova-site.invalid}"

echo "==> Ativando nginx HTTP-only (fase 1 — desafio ACME)..."
sed \
  -e "s/STORMPULSE_DOMAIN_PLACEHOLDER/$STORMPULSE_DOMAIN/g" \
  -e "s/ENZOVA_DOMAINS_PLACEHOLDER/$ENZOVA_SERVER_NAMES/g" \
  infra/tls/nginx-http.conf > infra/tls/nginx.conf.active
docker compose "${COMPOSE_FILES[@]}" up -d web

echo "==> Emitindo certificado Let's Encrypt para: ${STORMPULSE_DOMAIN} ${ENZOVA_SERVER_NAMES}..."
docker compose "${COMPOSE_FILES[@]}" run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  "${CERTBOT_DOMAIN_ARGS[@]}" \
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "==> Gerando config HTTPS..."
sed \
  -e "s/STORMPULSE_DOMAIN_PLACEHOLDER/$STORMPULSE_DOMAIN/g" \
  -e "s/ENZOVA_DOMAINS_PLACEHOLDER/$ENZOVA_SERVER_NAMES/g" \
  -e "s/CERT_DOMAIN_PLACEHOLDER/$STORMPULSE_DOMAIN/g" \
  infra/tls/nginx-https.conf > /tmp/nginx-https.conf.new

echo "==> Validando sintaxe antes de ativar..."
cp /tmp/nginx-https.conf.new infra/tls/nginx.conf.active
if ! docker compose "${COMPOSE_FILES[@]}" exec web nginx -t; then
  echo "!! nginx -t falhou na config nova — restaurando a config HTTP-only pra nao derrubar o site." >&2
  sed \
    -e "s/STORMPULSE_DOMAIN_PLACEHOLDER/$STORMPULSE_DOMAIN/g" \
    -e "s/ENZOVA_DOMAINS_PLACEHOLDER/$ENZOVA_SERVER_NAMES/g" \
    infra/tls/nginx-http.conf > infra/tls/nginx.conf.active
  docker compose "${COMPOSE_FILES[@]}" restart web
  exit 1
fi

echo "==> Ativando config HTTPS..."
docker compose "${COMPOSE_FILES[@]}" restart web

echo "==> Gravando infra/tls/.active-domains (pra infra/deploy.sh regenerar a"
echo "    config certo em deploys futuros, sem precisar re-interpretar nginx)..."
cat > infra/tls/.active-domains <<EOF
STORMPULSE_DOMAIN=$STORMPULSE_DOMAIN
ENZOVA_DOMAINS=$ENZOVA_SERVER_NAMES
CERT_DOMAIN=$STORMPULSE_DOMAIN
EOF

echo "==> Pronto. Teste: https://$STORMPULSE_DOMAIN/health"
for d in "${ENZOVA_DOMAINS[@]:-}"; do
  [ -n "$d" ] && echo "==> Teste: https://$d/"
done
echo "==> Lembre de configurar a renovacao automatica — ver infra/README.md § Renovacao do certificado."
