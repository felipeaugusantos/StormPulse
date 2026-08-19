# Infra 🔭

Configurações de infraestrutura para deploy (VPS Linux).

Nesta fase o ambiente de desenvolvimento é provido pelo
[`docker-compose.yml`](../docker-compose.yml) na raiz (Postgres+PostGIS, Redis,
API).

Previsto para fases futuras:

- `nginx/` — reverse proxy / TLS.
- compose/override de produção (API + workers Celery em containers separados).
