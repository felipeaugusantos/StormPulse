# ADR-0072 — Checagem de desmatamento (INPE DETER/PRODES) no talhão (item DETER)

- **Status:** Aceito
- **Data:** 2026-08-28

## Contexto

Levantamento de "que outra API pública geraria valor real pro sistema"
apontou dois candidatos com ROI claro para o mesmo público que já é a
tese de venda (banco/agrônomo avaliando talhão pra crédito rural):
**MapBiomas** (uso e cobertura do solo, série histórica) e **INPE
DETER/PRODES** (alertas de desmatamento). Dos dois, só o segundo foi
implementado agora — MapBiomas não tem uma API REST simples pra consultar
um polígono, só acesso via Google Earth Engine, que exige o usuário criar
uma conta/projeto no Google Cloud (mesma classe de dependência externa do
Sentinel Hub) — decisão explícita de adiar isso até essa conta existir.

## Decisão

### Fonte: WFS público do TerraBrasilis (INPE), sem credencial

Dois workspaces GeoServer confirmados ao vivo antes de escrever qualquer
código (`DescribeFeatureType`/`GetFeature` reais, 2026-08-28):

- `deter-amz:deter_amz` — alertas quase em tempo real, biomas Amazônia
  Legal + Pantanal + Amazônia não-florestada. Campos confirmados:
  `classname`, `view_date`, `uf`, `municipality`, `areamunkm`.
- `prodes-cerrado-nb:yearly_deforestation` — desmatamento anual (corte
  raso), bioma Cerrado. Campos confirmados: `class_name`, `image_date`/
  `year`, `state`, `area_km`.

Nenhum dos dois cobre Mata Atlântica/Pampa — um talhão em SP/PR/RS sempre
volta "nenhum alerta", que **não** é a mesma afirmação que "sem
desmatamento": é só "essas duas camadas não cobrem essa região". O
relatório deixa esse limite explícito em texto, nunca afirma ausência de
desmatamento fora dessas duas camadas.

### Ciclo de fundo semanal, nunca chamada ao vivo

Diferente do NDVI (chamada de imagem só quando o pipeline roda, mas a
Statistical API em si é relativamente estável), o WFS do TerraBrasilis se
mostrou **instável de verdade** em teste manual: mesmo uma consulta
`GetFeature` sem filtro nenhum falhou repetidas vezes com
`"Unable to obtain connection: ... pool error"` (erro do lado do banco do
próprio INPE) e timeouts de mais de 20 segundos numa consulta simples.
Uma chamada ao vivo no caminho de uma request (como o resumo por IA faz)
arriscaria travar a geração do relatório inteiro por causa de um serviço
de terceiro instável. Por isso isso roda como ciclo de fundo semanal
(`workers/deforestation_pipeline.py`, mesma cadência de "dado estático de
governo" já usada pelo ZARC) — o endpoint e o relatório só leem o que o
último ciclo bem-sucedido gravou, nunca consultam o INPE na hora.

### Uma linha por (talhão, fonte) — falha de uma nunca apaga a outra

DETER-AMZ e PRODES-Cerrado são consultados independentemente a cada
ciclo. Uma tabela nova, `DeforestationCheck`, guarda uma linha por
`(location_id, source)` — se DETER-AMZ falhar num ciclo mas
PRODES-Cerrado funcionar, só a linha do PRODES é atualizada; a última
leitura boa do DETER continua valendo até o próximo ciclo que funcionar.
Mesmo espírito de "nunca deixar uma falha parecer sucesso silencioso" já
usado no NDVI (`_persist_ndvi_image`), só que aplicado por fonte em vez de
por talhão, já que aqui existem duas fontes de verdade independentes.

### Filtro geométrico: `CQL_FILTER=INTERSECTS`, não `bbox=`

O parâmetro `bbox=` do WFS 2.0.0 depende da ordem de eixos declarada pela
CRS (EPSG:4674/4326 têm ordem lat/lon "oficial" segundo o registro EPSG,
mas GeoServer às vezes inverte isso silenciosamente conforme configuração
de compliance CITE) — risco real de inverter latitude/longitude sem
perceber. Um literal EWKT em `CQL_FILTER=INTERSECTS(geom,SRID=4326;
POLYGON((lon lat, ...)))` sempre usa ordem (lon, lat) por convenção,
evitando essa ambiguidade — e é uma interseção geométrica de verdade
(mais precisa que um bbox, que aceitaria falsos positivos de polígonos
que só tocam a caixa delimitadora).

## Verificação

`tests/test_deforestation_inpe.py` (`httpx.MockTransport`): formato da
consulta (ordem lon/lat no WKT), parsing dos dois formatos de resposta,
uma fonte falhando nunca derruba a outra nem levanta exceção, alertas
fora da janela de lookback são descartados. `tests/test_deforestation_pipeline.py`:
elegibilidade (mesma regra do NDVI — só talhão com contorno),
persistência por fonte, e o teste principal — uma fonte que falha num
ciclo posterior **nunca** sobrescreve o resultado bom anterior dessa
mesma fonte. `tests/test_integration_deforestation.py` (Postgres real):
404 sem checagem, alertas mesclados corretamente das duas fontes,
isolamento entre usuários, integração com `/agro/weekly-report`.
`tests/test_weekly_report_pdf_rendering.py` (+2 testes): renderiza sem
checagem nenhuma e com um alerta real. Suíte completa rodada (92.66% de
cobertura, gate de 85% ok).

## Consequências

- Mais uma tabela pequena (duas linhas por talhão elegível, nunca por
  ciclo — sem acúmulo).
- `DEFORESTATION_CHECK_ENABLED=false` por padrão — mesmo sem exigir
  credencial, liga sob decisão explícita do operador, não por padrão,
  dado o histórico de instabilidade do serviço observado em
  desenvolvimento.
- Cobertura geográfica parcial (só Amazônia/Cerrado) é uma limitação
  honesta do próprio INPE, não algo este projeto pode contornar sem outra
  fonte (MapBiomas, via Earth Engine, cobre o Brasil inteiro — item
  adiado, ver Contexto).
