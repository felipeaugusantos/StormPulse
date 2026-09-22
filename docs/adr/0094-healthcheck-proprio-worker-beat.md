# ADR-0094 — `worker`/`beat` ganham healthcheck próprio (não mais HTTP)

- **Status:** Aceito
- **Data:** 2026-09-22

## Contexto

Achado ao investigar o incidente da ADR-0093: `docker compose ps` sempre
mostrava `worker` e `beat` como `(unhealthy)`, mesmo funcionando
normalmente (confirmado ao vivo pelos próprios logs — `beat` disparando
as tarefas nos horários certos, `worker` de fato chamando o radar do
INMET). Causa: o `HEALTHCHECK` do `backend/Dockerfile` testa
`http://127.0.0.1:8000/health` — certo pra `api`, mas `worker`/`beat`
rodam Celery (`command:` sobrescrito no `docker-compose.yml`), nunca um
servidor HTTP, então essa porta nunca escuta ali e o check falha pra
sempre, incondicionalmente.

## Decisão

**Healthcheck sobrescrito por serviço no `docker-compose.yml`, não uma
mudança no `Dockerfile`.** A imagem é a mesma pros três serviços
(`api`/`worker`/`beat`) — mudar o `HEALTHCHECK` da imagem quebraria a
`api`, que precisa mesmo do check HTTP. `healthcheck:` do Compose
sobrescreve o da imagem por container, sem tocar no Dockerfile nem exigir
uma variante de imagem só pra isso.

**`worker`: `celery inspect ping`.** Padrão já documentado pelo próprio
Celery — a checagem de fato ida-e-volta pelo broker (Redis) até o
processo worker e de volta, confirma que ele está vivo e respondendo, não
só que o processo existe. Confirmado ao vivo (`docker exec ... celery
inspect ping` → `pong`, exit 0).

**`beat`: frescor do arquivo de schedule, não um processo genérico
"tá rodando".** Beat não consome tarefa nenhuma — não existe um
`inspect ping` equivalente pra ele. `celery beat` reescreve seu arquivo
de agendamento (`/tmp/celerybeat-schedule`, o mesmo caminho já passado em
`--schedule`) toda vez que o horário da última execução de uma entrada
muda — confirmado ao vivo que o `mtime` desse arquivo avança a cada
~60s, batendo com o intervalo mais apertado do próprio projeto
(`deliver-notifications-every-minute`/`alert-delivery-every-minute`,
`workers/celery_app.py`). O check compara `mtime` contra `date +%s` e
falha se passou de 150s — bem mais folgado que o intervalo real, não um
prazo apertado por acidente.

## Verificação

Reproduzido ao vivo num ambiente isolado: `docker compose up -d --build
worker beat` com os healthchecks novos — os dois reportam `(healthy)`
depois do `start_period`. `docker compose config` (dev e prod) segue
válido.

## Consequências

- Nenhuma mudança de comportamento real do `worker`/`beat` — só a
  observabilidade de `docker compose ps`/scripts de deploy que dependem
  de `condition: service_healthy` fica honesta.
- `infra/deploy.sh`'s `verify_stack_healthy()` continua checando só
  `api` via `/health` — não dependia do status Docker de `worker`/`beat`
  pra decidir sucesso/rollback, então esse incidente nunca foi a causa
  real de um rollback falhar (só deixava `docker compose ps` mentindo).
- Se o `backend/Dockerfile` ganhar um novo serviço baseado na mesma
  imagem no futuro, mesma regra: healthcheck sobrescrito no
  `docker-compose.yml` daquele serviço, nunca assumir que o `HEALTHCHECK`
  da imagem serve pra todo mundo que a usa.
