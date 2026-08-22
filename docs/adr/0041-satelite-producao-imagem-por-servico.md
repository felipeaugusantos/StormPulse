# ADR-0041 — Satélite em produção: imagem só no worker, extensão regional

- **Status:** Aceito
- **Data:** 2026-08-22
- **Decisão do dono do produto**: ativar observação via satélite em
  produção mesmo no t3.small, mitigando o custo de RAM restringindo a
  variante pesada só ao serviço que precisa dela, e a área processada só
  à região da localidade monitorada (não o Brasil inteiro).

## Contexto

`docker-compose.prod.yml` usava uma única variável (`STORMPULSE_IMAGE`)
pros três serviços Python (`api`, `worker`, `beat`) — ativar satélite
trocando essa variável pra `-satellite` colocaria os **três** na imagem
pesada (~1.9GB, GDAL+numpy+scipy+opencv), mesmo `api` e `beat` nunca
importando GDAL/TATHU (confirmado: `grep -rn "import osgeo\|import
tathu" app/` não encontra nada — só
`workers/satellite_pipeline.py` usa).

Além disso, `SATELLITE_EXTENT` (padrão `-74,-34,-34,6`) cobre o Brasil
inteiro — processamento e download desnecessários pra uma instalação
monitorando uma localidade específica (Ribeirão Preto/SP, no caso).

## Decisão

**Imagem satélite só no `worker`**: nova variável `STORMPULSE_WORKER_IMAGE`
(com fallback pra `STORMPULSE_IMAGE`, que continua valendo pra `api`/`beat`)
— só ela precisa apontar pra tag `-satellite`. `.env` do servidor:

```bash
SATELLITE_ENABLED=true
STORMPULSE_WORKER_IMAGE=ghcr.io/felipeaugusantos/stormpulse:latest-satellite
```

**Extensão regional em vez de nacional**: `SATELLITE_EXTENT` recalculado
pra uma janela ao redor da localidade monitorada, em vez do padrão
(Brasil inteiro). Pra Ribeirão Preto (-21.18, -47.81), uma janela de ~7°
de longitude por 6° de latitude ao redor do ponto:

```bash
SATELLITE_EXTENT=-51,-24,-44,-18
```

Reduz a área processada a cada ciclo em ~97% (de ~1600 graus² pra ~42
graus²) — impacto direto em RAM/CPU/tempo de cada ciclo de detecção,
exatamente o gargalo que motivava não ligar satélite num t3.small.
**Efeito colateral aceito**: uma tempestade formando-se fora dessa janela
(em outro estado, por exemplo) não seria detectada — trade-off explícito
do dono do produto, não um bug. Se locais monitorados forem adicionados
fora dessa região no futuro, `SATELLITE_EXTENT` precisa ser revisado.

## Consequências

- `api` e `beat` continuam na imagem `runtime-base` (~430MB) — só `worker`
  sobe pra ~1.9GB.
- Nenhuma mudança de regra, threshold ou modelo de detecção — só qual
  imagem cada serviço usa e qual janela geográfica é processada,
  parâmetros de deploy/config, não de classificação meteorológica.
- `docker-publish.yml` já publicava a tag `-satellite` desde a Fase 7
  (ADR-0032) — nenhuma mudança de CI necessária, só de config do servidor.
