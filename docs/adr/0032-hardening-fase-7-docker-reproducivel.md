# ADR-0032 — Hardening (Fase 7): Docker reproduzível + imagem satélite opcional

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

`backend/Dockerfile` tinha três problemas de reprodutibilidade:

1. **TATHU instalado de uma branch flutuante** (`git+...@master`) — o
   conteúdo pode mudar a qualquer momento, sem nenhum sinal no histórico
   deste repositório. Um rebuild em dias diferentes podia trazer código
   TATHU diferente silenciosamente.
2. **Imagem base sem pin de digest** (`python:3.12-slim`, só a tag) — a tag
   é um ponteiro móvel; o Docker Hub pode apontar `3.12-slim` para uma
   imagem diferente sem aviso.
3. **GDAL/TATHU sempre instalados**, mesmo que `SATELLITE_ENABLED=false`
   (o padrão do projeto, ver `.env.example`) nunca use nenhum dos dois em
   tempo de execução — toda instalação carrega ~1.5GB de dependências
   (GDAL, numpy, scipy, opencv, rasterio, netCDF4...) sem necessidade.

## Decisão

### TATHU pinado a um commit SHA auditado

```dockerfile
ARG TATHU_COMMIT_SHA=64f970eccad8f702498afd97c97b1a70afeecc10
RUN ... pip install --no-deps "git+https://github.com/uba/tathu.git@${TATHU_COMMIT_SHA}"
```

Auditoria feita nesse SHA antes de fixá-lo (2026-08-22): repositório
oficial do INPE (`uba/tathu`), licença MIT, sem `eval`/`exec`/import
dinâmico/execução de string de shell em nenhum lugar do pacote —
único uso de `subprocess` é `Popen` com lista de argumentos em
`tathu/downloader/mergir.py`, um módulo de download que este projeto
nunca importa (só as peças de detecção/tracking, via `workers/satellite_pipeline.py`).
Atualizar essa versão no futuro exige trocar o SHA deliberadamente e repetir
essa revisão — nunca mais um `@master` implícito.

### Imagem base pinada por digest

```dockerfile
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS base
```

Mesmo princípio: a tag `3.12-slim` continua no comentário para
legibilidade humana, mas o build resolve sempre o mesmo digest até
alguém trocar deliberadamente (o Dependabot do ecossistema `docker` já
cobre `backend/Dockerfile`, então esse pin também recebe PRs automáticos
quando uma nova imagem base sai).

### Duas variantes de imagem: `runtime-base` e `runtime-satellite`

O Dockerfile ganhou dois pares builder/runtime:

- `builder-base` → `runtime-base`: só as dependências do `pyproject.toml`
  principal (sem o extra `satellite`). Usuário non-root preservado,
  healthcheck preservado.
- `builder-satellite` (estende `builder-base`) → `runtime-satellite`
  (estende `runtime-base`, sobrescrevendo o venv): adiciona
  `gdal-bin`/`libgdal-dev`/`git` no builder, instala o extra `satellite` +
  TATHU, e no runtime só adiciona a lib GDAL de sistema.

`docker-compose.yml` seleciona a variante via `${API_DOCKER_TARGET:-runtime-base}`
nos serviços `api` e `worker` (o `worker` roda o pipeline de satélite via
Celery). O serviço `beat` fica travado em `runtime-base` sempre —
`workers/celery_app.py` só referencia nomes de task como string no
`beat_schedule`, nunca importa `workers.tasks` (e portanto nunca importa
GDAL/TATHU), então não há razão para pagar o peso da imagem maior ali.

`.env.example` documenta a nova variável ao lado de `SATELLITE_ENABLED`
(que continua `false` por padrão) — trocar as duas juntas é o contrato:
`SATELLITE_ENABLED=true` sem `API_DOCKER_TARGET=runtime-satellite` teria a
flag de aplicação ligada mas as libs ausentes na imagem (falharia no
import, de forma óbvia — não silenciosamente incorreto).

### CI e publicação

- `ci.yml`: `docker compose build` continua construindo só a variante
  padrão (`runtime-base`, mais rápida — CI não seta `API_DOCKER_TARGET`),
  preservando o smoke test completo existente (health/readiness/migrações/
  auth/locations/pipeline) exatamente como antes. Um step novo,
  `docker build --target runtime-satellite`, garante que a variante
  satélite também builda (pega quebra de pin do GDAL/TATHU) sem pagar o
  custo de outro boot de stack completo. Um step de comparação de tamanho
  imprime os dois tamanhos no log.
- `docker-publish.yml`: matriz com duas entradas (`runtime-base` sem
  sufixo de tag, `runtime-satellite` com sufixo `-satellite`), cache do
  GHA por variante (`scope`) para não misturar camadas incompatíveis.

## Comparação medida (build local, 2026-08-22)

| Variante | Tamanho da imagem | Tempo de build (frio, sem cache) |
|---|---|---|
| `runtime-base` | 432 MB | ~1min |
| `runtime-satellite` | 1.92 GB | ~5min |

Confirmado também que a stack inteira (`docker compose up -d`, variante
`runtime-base` padrão) sobe saudável, `/health` e `/ready` respondem
corretamente, `alembic upgrade head` roda a cadeia completa de migrações
(inclusive a baseline congelada da Fase 6, ADR-0031) contra um Postgres
real do compose.

## Hashes para dependências de produção (avaliado, não implementado)

O `pyproject.toml` usa especificadores de faixa (`fastapi>=0.115`, etc.),
não pins exatos — `pip install --require-hashes` exigiria um lockfile
completo (`pip-compile`/`uv lock` ou equivalente) gerado e mantido à parte,
mudança de fluxo maior que o escopo desta fase. Avaliação: o
`pip-audit` já rodado no CI (`ci.yml`, job `backend`) cobre a superfície de
risco mais relevante (vulnerabilidades conhecidas em versões resolvidas),
e o pin por digest da imagem base + SHA do TATHU já elimina as duas fontes
de não-determinismo mais graves (uma dependência git flutuante e uma tag
de imagem flutuante). Hash-pinning completo do restante das dependências
Python fica como item futuro, não bloqueante.

## Consequências

- Nenhuma mudança de comportamento para quem já roda com
  `SATELLITE_ENABLED=false` (o padrão) — a imagem resultante é
  funcionalmente idêntica, só menor.
- Quem precisa da observação por satélite ativa os dois flags juntos
  (`SATELLITE_ENABLED=true` + `API_DOCKER_TARGET=runtime-satellite`).
- Reprodutibilidade: rebuildar a imagem em qualquer máquina, em qualquer
  data, até o próximo bump deliberado, resolve exatamente os mesmos bytes
  de base Python e exatamente o mesmo código TATHU.
- Fora de escopo: hash-pinning completo das dependências Python (avaliado
  acima, não implementado); nenhuma mudança de modelo, regra ou threshold
  meteorológico.
