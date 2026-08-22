#!/usr/bin/env bash
# StormPulse — renovacao do certificado Let's Encrypt (rodar via cron,
# ver infra/README.md). Certificados do Let's Encrypt duram 90 dias;
# `certbot renew` so renova de fato quando falta <30 dias — seguro rodar
# com frequencia.

set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

docker compose "${COMPOSE_FILES[@]}" run --rm certbot renew --webroot -w /var/www/certbot
docker compose "${COMPOSE_FILES[@]}" exec web nginx -s reload
