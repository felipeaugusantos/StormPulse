# ADR-0013 — Imagem de satélite ao vivo no mapa

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** FASE 18 — visualização da imagem IR do GOES-19, não só os pontos detectados

## Contexto

Você perguntou se a imagem de satélite podia aparecer "ao vivo" no mapa, não
só os pontos de observação (`ConvectiveWatch`) já existentes desde a FASE
16. O pipeline (`backend/workers/satellite_pipeline.py`) já baixa a banda 13
(IR) do GOES-19 e reprojeta com `tathu.satellite.goes_r.sat2grid` (GDAL, em
memória) só para detectar núcleos convectivos — a imagem em si sempre foi
descartada depois do processamento.

Inspecionei o código-fonte real do TATHU (`goes_r.sat2grid`) e confirmei que
ele devolve um `gdal.Dataset` em memória já em Kelvin real e georreferenciado
exatamente no bbox configurado — dá pra gerar uma imagem diretamente desse
mesmo grid, sem baixar/reprojetar de novo.

## Decisão

- **Reaproveita o grid já reprojetado**: `_detect_systems` (em
  `workers/satellite_pipeline.py`) agora também renderiza a imagem a partir
  do mesmo `grid`, retornando ambos via `_CycleArtifacts` — sem 2ª chamada
  ao STAC nem 2ª reprojeção GDAL.
- **Convenção de cor**: escala de cinza invertida (nuvem fria = branco,
  superfície quente = preto) — a mesma usada mundialmente em produtos de
  satélite IR, não uma paleta inventada. Implementada em
  `_render_ir_image`, função pura (array numpy → PNG), sem GDAL, testável
  isoladamente (`tests/test_satellite_image_render.py`).
- **Downsample para ~800px**: o grid nativo (resolução de 4km sobre o bbox
  do Brasil) dá ~1100×1100px; reduzido porque é uma imagem de *exibição*,
  não um dado científico bruto.
- **Só a imagem mais recente é guardada**: novo modelo `SatelliteImage`
  (tabela `satellite_images`) — cada ciclo apaga a linha anterior e insere
  uma nova, mesmo espírito de `_prune_stale_watches`/
  `_prune_old_mock_cells`. Sem histórico — não há caso de uso pra isso
  ainda.
- **Endpoint público, não autenticado — por necessidade técnica, não só
  simplicidade**: a camada `image` do MapLibre busca a URL direto via
  `fetch()` do navegador, sem o header `Authorization` que o resto do app
  usa. Novo `GET /api/v1/public/satellite/image` (metadados JSON:
  `captured_at`, `bbox`, `band`, `width`, `height`) e
  `GET /api/v1/public/satellite/image.png` (bytes crus,
  `Cache-Control: no-cache`) — mesmo precedente de
  `/api/v1/public/satellite/watches` (FASE 15/16). Dashboard autenticado e
  modo visitante usam o mesmo endpoint público — sem rota autenticada
  duplicada.
- **Frontend**: nova camada `image` no MapLibre (`StormMap.tsx`), abaixo da
  camada de watches (nunca compete visualmente com pontos), com checkbox
  "mostrar imagem de satélite" (ligado por padrão) e frescor exibido via
  `timeAgo` (reaproveita `web/src/format.ts`, criado nesta sessão para o
  painel de watches).

## Achado incidental: `0001_bootstrap` "vivo" quebrava CI

Durante a implementação, você mandou o log de um CI quebrado. Investigando,
a causa era anterior a esta feature — ver [ADR-0012](0012-bootstrap-migration-idempotente.md) — mas a nova migration
(`satellite_images`) também precisou do mesmo guard de existência por estar
sujeita ao mesmo problema.

## Verificação

- `pytest tests/test_satellite_image_render.py` — colorização/downsample
  isolados (skip automático se `numpy`/`Pillow` não estiverem instalados,
  fora do extra `satellite`).
- `pytest tests/test_integration_public_router.py` — endpoints públicos
  (404 honesto sem imagem, 200 com metadados/PNG corretos).
- Ao vivo: rodei dois ciclos reais de satélite (`SATELLITE_ENABLED=true`) —
  confirmado no banco que `satellite_images` nunca acumula (sempre 1 linha),
  confirmado visualmente que a imagem renderizada é uma imagem IR real e
  reconhecível do Brasil (litoral, bandas de nuvem, sistema frontal visível
  no sul — bate com os `ConvectiveWatch`s detectados na mesma região).
- **Limitação conhecida**: não foi possível confirmar visualmente a camada
  *dentro do mapa* neste ambiente de teste — o navegador do sandbox não tem
  saída de rede para os tiles do OpenStreetMap, então o evento `load` do
  MapLibre nunca completa aqui (confirmado: zero requisições de tile em
  toda a sessão, para qualquer camada, não só esta). Backend e integração
  de dados foram verificados de ponta a ponta; só o render visual final no
  WebGL não pôde ser confirmado neste ambiente específico.
