# ADR-0042 — Fase 1: passagem de variáveis no Docker Compose

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

`docker-compose.yml` enumerava manualmente cada variável de ambiente que
`api`/`worker`/`beat` deveriam receber, no formato `VAR: ${VAR:-default}`.
Isso funciona só até alguém adicionar um campo novo em `Settings`
(`app/core/config.py`) e documentá-lo no `.env.example` sem lembrar de
também adicionar a linha correspondente nos três blocos de `environment:`
do Compose.

Auditoria sistemática (todos os 83 campos de `Settings` comparados contra
o que `docker compose config` realmente resolve pros três serviços)
confirmou que isso já tinha acontecido — **nunca chegavam ao container**:
`TRUSTED_PROXY_IPS`, todos os 7 campos `REFRESH_COOKIE_*`, os 3 `OTEL_*`,
todos os `INMET_*`/`CPTEC_*`/`OPEN_METEO_*` (URLs, timeouts, tokens), todos
os `AGRO_*`, e **`SATELLITE_EXTENT`** — este último descoberto porque a
extensão regional configurada horas antes desta ADR (`-51,-24,-44,-18`,
pra cobrir só a região de Ribeirão Preto — ver ADR-0041) nunca tinha
efeito real: o worker continuava processando o Brasil inteiro
(`-74,-34,-34,6`, o default do código), silenciosamente.

## Decisão

Trocado `environment:` (enumeração manual) por `env_file: - path: .env
required: false` em `api`/`worker`/`beat` — carrega o arquivo `.env` do
projeto inteiro de uma vez, eliminando a classe inteira de "esqueci de
enumerar essa variável nova". Mantido um `environment:` pequeno (via YAML
anchor `&service_env_overrides`, compartilhado pelos três serviços) só
pros valores que **precisam** diferir dentro da rede Docker —
`POSTGRES_HOST`/`REDIS_HOST` apontam pro hostname interno (`db`/`redis`),
não pro `localhost` que o `.env.example` documenta pra uso fora de
container. `environment:` sempre vence sobre `env_file` no Compose, então
essa sobreposição é garantida.

`db`/`redis`/`web`/`certbot` **não** ganharam `env_file` — não usam
`Settings`, receber essas variáveis seria exposição desnecessária
(instrução explícita: banco/frontend só recebem o que realmente
precisam).

**Duas lacunas adicionais encontradas e corrigidas** na auditoria:
`.env.example` nunca documentava `OTEL_ENABLED`/`OTEL_SERVICE_NAME`/
`OTEL_EXPORTER_OTLP_ENDPOINT` (então nem `env_file` teria como passá-los —
o arquivo não tinha a linha) nem `APP_NAME`, `READINESS_TIMEOUT_SECONDS`,
`LIGHTNING_HTTP_TIMEOUT_SECONDS`, `LIGHTNING_RETENTION_MINUTES`,
`AGRO_FROST_LIGHT_THRESHOLD_C`, `AGRO_SPRAY_INVERSION_MAX_WIND_KMH`,
`AGRO_SPRAY_INVERSION_MIN_HUMIDITY_PERCENT` — todos adicionados.

## Verificação

`infra/verify_compose_env.py` — escreve um `.env` sentinela temporário
(faz backup e restaura qualquer `.env` real existente, nunca toca em
segredo de verdade), roda `docker compose config --format json` pro
compose de dev e pro overlay de produção, e confirma programaticamente
que os valores sentinela aparecem em `api`/`worker`/`beat` e **não**
aparecem em `db`/`redis`. Rodado manualmente contra os 83 campos de
`Settings` (zero ausentes agora) e integrado como step no CI
(`.github/workflows/ci.yml`, job `docker`).

Testado também de ponta a ponta com a stack real (`docker compose up
-d --build`): `/health`/`/ready` respondendo, `worker`/`beat` subindo sem
erro de validação, e confirmado dentro do container
(`python -c "from app.core.config import get_settings; ..."`) que os
valores do `.env` realmente chegam ao processo Python.

## Consequências

- Qualquer variável nova adicionada ao `.env.example` a partir de agora
  chega automaticamente aos três serviços — não é mais possível repetir
  essa classe de bug sem também quebrar `verify_compose_env.py` no CI.
- `docker-compose.prod.yml` não precisou de nenhuma mudança — herda o
  `env_file` do arquivo base via merge, sem sobrescrever `environment:`.
- Nenhuma mudança de comportamento pra quem já roda com os valores padrão
  do `.env.example` — só passa a existir a possibilidade real de ajustar
  o que já era documentado como ajustável.
