# ADR-0009 — Observação via satélite (GOES-19 + TATHU)

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 16

## Contexto

Você perguntou se o sistema consegue monitorar em tempo real a movimentação
das nuvens para saber se uma formação pode virar chuva antes de aparecer em
radar/pluviômetro. Pesquisa confirmou dois recursos públicos e gratuitos:

- **INPE STAC** (`data.inpe.br/bdc/stac/v1`, parte do Brazil Data Cube):
  catálogo padronizado com imagens do GOES-19 a cada ~10 min, disco cheio,
  sem autenticação. Verificado ao vivo.
- **TATHU** (`github.com/uba/tathu`, MIT, mantido pelo próprio INPE):
  biblioteca Python para detectar/rastrear sistemas convectivos a partir da
  banda infravermelha (10.3µm) via limiar de temperatura de topo de nuvem —
  a técnica padrão da meteorologia para "convecção crescendo antes de
  chover". Sua arquitetura (`detectors`→`descriptors`→`trackers`→
  `forecasters`) espelha o que já existe em `engine/detection`→
  `engine/tracking`→`engine/trajectory`, mas para satélite em vez de
  estações de chuva.

## Decisões

### TATHU não está no PyPI

`pip install tathu` **não existe** — o INSTALL.rst do projeto só documenta
conda/mamba. Instalado direto do GitHub
(`pip install --no-deps git+https://github.com/uba/tathu.git@master`) com
suas dependências reais de runtime listadas manualmente em
`pyproject.toml` (extra `satellite`), derivadas do `env.yml` do projeto
menos o que é só para plotting/docs (`cartopy`, `geopandas`, `sphinx*`) —
não usamos `MapView` (matplotlib), o mapa já é o MapLibre do dashboard.

### GDAL: extra opcional, não dependência principal

GDAL precisa da versão Python bater exatamente com a `libgdal` do sistema
(`pip install "GDAL==$(gdal-config --version)"`) — não dá para fixar uma
versão única em `pyproject.toml`. Ficou num extra `[satellite]`, instalado
só no Dockerfile (builder: `gdal-bin libgdal-dev`, runtime: `gdal-bin` de
novo, só pelas libs compartilhadas) — um venv de desenvolvimento comum
(inclusive o usado nesta sessão, Windows sem GDAL) continua instalável
normalmente com `pip install -e ".[dev]"`.

### Fonte de download: nosso próprio STAC, não o downloader do TATHU

O exemplo oficial do TATHU baixa do bucket AWS `noaa-goes16` — mas GOES-16
parou de transmitir depois que GOES-19 assumiu como GOES-East (abr/2025).
Em vez de confiar que a chave `'GOES-19'` já existe no dicionário
`AWS.buckets` da versão instalada, escrevemos nosso próprio download via
`httpx` contra o STAC do INPE (mesmo estilo do `InmetWeatherProvider`,
FASE 13) — só a banda 13 de 1 frame por ciclo (não 2: velocidade/direção
vêm da comparação com o estado anterior já persistido no banco, o mesmo
espírito de `pipeline_service.py`, mais barato que baixar 2 frames toda
vez).

### Rastreamento próprio, não `trackers`/`forecasters` do TATHU

TATHU tem módulos prontos de rastreamento (`OverlapAreaTracker`) e previsão
(`Conservative`), mas exercitá-los corretamente exigiria confiar numa
superfície de API que não testamos rodando de verdade. Em vez disso:
associação por centróide mais próximo (reusa `engine/geo.haversine_km`/
`bearing_deg`, já testados) entre a nova detecção e os `ConvectiveWatch`
ativos no banco — mesmo espírito do `engine/tracking/tracker.py` já
existente, só que mais simples. A API real do TATHU que *usamos* (
`ConvectiveSystem.getCentroid()`, `.getGeomWKT()`, `.attrs` populado por
`StatisticalDescriptor`) foi lida diretamente do código-fonte antes de
escrever a integração — não adivinhada.

### `ConvectiveWatch`, não `StormCell`

Uma nuvem fria no topo é um sinal **diferente** de uma célula de chuva já
detectada — misturar exigiria fabricar uma refletividade falsa a partir de
Kelvin (proibido pelo ADR-0005). Refletividade aqui não existe: usamos a
temperatura de brilho mínima (Kelvin) diretamente, sem converter para dBZ.

### Alertas: eventos novos, nível fixo YELLOW

`AlertEngine.decide()` é construído em cima de `RiskAssessment` (scores de
chuva/vento/granizo/raio) — não cabe um sinal de satélite sem inventar
números. `workers/satellite_pipeline.py` tem sua própria decisão, mas
reusa o mesmo mecanismo de idempotência (`Alert.dedup_key` único por
tenant) e as mesmas tabelas `Alert`/`Notification`. Dois eventos novos
(`SATELLITE_WATCH_DETECTED`, `SATELLITE_WATCH_DISSIPATED`), nível sempre
`YELLOW` — mais baixo que os alertas de tempestade confirmada, nunca
calculado a partir só da temperatura (seria fabricar uma precisão que não
existe). Novo `alerts.convective_watch_id` (FK nullable, mesmo padrão de
`storm_cell_id`).

### Armadilha real: enum nativo do Postgres não é a `.value` do Python

`sa.Enum(AlertEventType, ...)` guarda o **nome** do membro Python
(`SATELLITE_WATCH_DETECTED`, maiúsculo), não `.value`
(`satellite_watch_detected`) — confirmado direto no banco (`STORM_DETECTED`
etc. já maiúsculos). A primeira versão da migration usou minúsculo e
quebrou em teste real; corrigida para maiúsculo. Documentado aqui para não
se repetir na próxima vez que um enum ganhar um valor novo.

### Desligado por padrão

`SATELLITE_ENABLED=false` — arquivo de ~20-30MB baixado e reprojetado via
GDAL a cada ciclo é custo real de infra, não algo para ligar sem intenção.

## Verificação feita

Rodado de ponta a ponta contra dados reais (não simulados) dentro do
container Docker com GDAL: baixou a banda 13 mais recente do GOES-19,
reprojetou, detectou **20 sistemas convectivos reais sobre o Brasil** (topo
entre 198K e 224K, região amazônica principalmente — condizente com
convecção tropical intensa), persistiu, e apareceu no dashboard (autenticado
e modo visitante) sem erros de console.

## Fora do escopo (documentado, não escondido)

- `trackers`/`forecasters` do TATHU (previsão de posição futura em
  +30/60/90/120min) — a associação por centróide mais próximo cobre o
  essencial (continuidade + velocidade/direção) sem depender de uma API não
  testada.
- Testes de CI para `_detect_systems` (o passo com GDAL) — precisaria de
  GDAL instalado no runner e um arquivo de satélite de fixture; verificado
  manualmente, como a previsão do INMET (FASE 15).
- Persistir/expor via API os campos `mean`/`std` (só `min`/`count` são
  usados hoje).
- Ajuste fino de `SATELLITE_THRESHOLD_KELVIN`/`SATELLITE_MIN_AREA_KM2`
  contra meteorologistas de verdade — os valores (230K, 3000km²) vêm do
  exemplo oficial do TATHU, não validados especificamente para o Brasil.
