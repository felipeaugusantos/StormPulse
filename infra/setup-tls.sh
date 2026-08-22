#!/usr/bin/env bash
# StormPulse — configuracao unica de TLS via Let's Encrypt (metodo webroot).
#
# Uso: ./infra/setup-tls.sh <dominio> <email>
# Exemplo (sem dominio proprio, usando nip.io):
#   ./infra/setup-tls.sh 100-48-193-126.nip.io voce@example.com
#
# Pre-requisito: a stack ja deve estar rodando com
# docker-compose.prod.yml (ver infra/README.md) e a porta 80 acessivel
# publicamente no dominio informado — o Let's Encrypt precisa alcancar
# esse endereco pra validar o desafio ACME.

set -euo pipefail

DOMAIN="${1:?Uso: $0 <dominio> <email>}"
EMAIL="${2:?Uso: $0 <dominio> <email>}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

echo "==> Ativando nginx HTTP-only (fase 1 — desafio ACME)..."
cp infra/tls/nginx-http.conf infra/tls/nginx.conf.active
docker compose "${COMPOSE_FILES[@]}" up -d web

echo "==> Emitindo certificado Let's Encrypt para $DOMAIN..."
docker compose "${COMPOSE_FILES[@]}" run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "==> Ativando config HTTPS..."
sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" infra/tls/nginx-https.conf > infra/tls/nginx.conf.active
docker compose "${COMPOSE_FILES[@]}" restart web

echo "==> Pronto. Teste: https://$DOMAIN/health"
echo "==> Lembre de configurar a renovacao automatica — ver infra/README.md § Renovacao do certificado."
