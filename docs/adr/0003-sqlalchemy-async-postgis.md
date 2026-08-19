# ADR-0003 — Persistência: SQLAlchemy async + asyncpg + GeoAlchemy2/PostGIS

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 0 (modelos na FASE 2)

## Contexto

A API FastAPI é async e faz consultas geoespaciais (proximidade de células a
locais). Precisamos de ORM, driver e camada geográfica.

## Decisão

- **ORM:** SQLAlchemy 2.0 (estilo declarativo tipado) em modo **async**.
- **Driver:** `asyncpg` (via `postgresql+asyncpg`).
- **Geo:** **GeoAlchemy2** sobre **PostGIS**, usando `geography(…, 4326)`.
- **Migrations:** Alembic.

## Justificativa

- SQLAlchemy 2.0 async integra-se naturalmente ao FastAPI async e evita bloquear
  o event loop em I/O de banco.
- `asyncpg` é o driver Postgres async mais rápido e maduro.
- PostGIS + GeoAlchemy2 dão consultas de proximidade eficientes
  (`ST_DWithin` sobre `geography`), essenciais para "células dentro de X km de
  um local".
- Alembic é o padrão de migrations do ecossistema SQLAlchemy.

### Desvantagens aceitas

- Código async exige disciplina (sessões por request, sem I/O síncrono no loop).
- Alguns workers CPU-bound do engine podem ser **síncronos** — e tudo bem:
  usamos async só onde há benefício real de I/O (regra YAGNI para async).

## Consequências

- Sessão async gerenciada por dependência do FastAPI; readiness faz `SELECT 1`.
- Imagem Docker do Postgres é `postgis/postgis` (Postgres + extensão PostGIS).
- A extensão PostGIS é habilitada via migration/inicialização, não no código.
