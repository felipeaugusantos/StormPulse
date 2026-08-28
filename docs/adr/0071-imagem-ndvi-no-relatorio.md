# ADR-0071 — Imagem colorida de NDVI no relatório semanal

- **Status:** Aceito
- **Data:** 2026-08-28

## Contexto

Item "imagem do talhão": além do número de NDVI e da explicação textual
(ADR-0070 cobriu área e resumo por IA), pediu-se uma imagem visual do
vigor da vegetação — mais fácil de interpretar de relance do que um
número sozinho, e mais forte visualmente num documento pra banco/
agrônomo.

## Decisão

### Fonte: Process API do Sentinel Hub, não a Statistical

A leitura numérica (`get_ndvi`) já usa a Statistical API do Sentinel Hub,
que só devolve estatísticas agregadas, nunca pixel a pixel. Uma imagem
colorida precisa da **Process API** — um endpoint diferente, que renderiza
o `evalscript` e devolve os bytes da imagem já prontos (PNG), sem
processamento local nenhum. Novo `NdviProvider.get_ndvi_image`, evalscript
próprio com uma rampa de cor simples (vermelho/marrom → amarelo → verde)
e, diferente do evalscript numérico existente, mascarando nuvem/sombra/
neve de verdade via SCL (o numérico só usava `dataMask`, uma lacuna
identificada mas deixada de fora de escopo aqui — o numérico já está em
produção há tempo, mudar sua semântica histórica é uma decisão separada).

### Persistência: só a mais recente, igual ao SatelliteImage

Diferente do resumo por IA (ADR-0070), que é barato e gerado sob demanda
a cada abertura do relatório, uma chamada à Process API é mais pesada e
sujeita a cota — o próprio endpoint `/agro/ndvi` já documenta essa
preocupação ("nunca chama o provedor ao vivo... cota limitada"). Por
isso a imagem é gerada **uma vez por ciclo do pipeline** (a cada 8h, junto
da leitura numérica) e guardada em `NdviImage`, uma tabela nova — só a
mais recente é mantida por talhão (`UniqueConstraint` em `location_id`,
substituída a cada ciclo), mesmo espírito de "podar, não acumular" do
`SatelliteImage` já existente, só que por talhão em vez de global.

Falha ao buscar a imagem nunca desfaz a leitura numérica do mesmo ciclo —
é um bônus em cima do número, não um requisito pra ele.

### Pillow virou dependência base, não só do container satélite

Embutir a imagem no PDF usa `reportlab.platypus.Image`, que **exige**
Pillow pra decodificar o PNG (confirmado lendo o código-fonte do
reportlab: `ImageReader._read_image` chama `PIL.Image.open` direto, sem
alternativa pura em Python). O container `api` de produção nunca teve
Pillow — só o `-satellite` tinha, via seu extra `[satellite]`. Diferente
de GDAL/numpy/TATHU (que existem só pra funcionalidade opcional de
satélite, e por isso ficam fora da imagem base por tamanho), o endpoint
de PDF é sempre ativo — então Pillow virou dependência base mesmo,
retirada do extra `[satellite]` pra não duplicar.

Esse problema foi pego ANTES de ir pra produção: um teste unitário novo
(`test_weekly_report_pdf_rendering.py`) monta um PDF de verdade com uma
imagem PNG de verdade embutida — sem o Pillow como dependência base, esse
teste teria falhado exatamente do jeito que o endpoint real falharia.

### Endpoint próprio, não dentro do JSON do relatório

`GET /locations/{id}/agro/ndvi-image` devolve os bytes crus (`image/png`),
separado do JSON do relatório — mesmo padrão já usado pro PDF
(`/agro/weekly-report/pdf`), já que bytes binários não pertencem numa
resposta JSON. O endpoint do PDF busca a imagem já guardada (uma consulta
no banco, não uma chamada nova à Sentinel Hub) e embute no documento.

## Verificação

`tests/test_ndvi_sentinel_hub.py` (+2 testes, `httpx.MockTransport`):
formato da requisição à Process API, bytes crus devolvidos, falha de rede
embrulhada. `tests/test_ndvi_pipeline.py` (+3 testes): imagem persistida
junto da leitura bem-sucedida, substituída (não acumulada) entre ciclos,
falha na imagem não desfaz a leitura numérica. `tests/test_integration_ndvi.py`
(+3 testes, Postgres real): 404 sem imagem, bytes corretos com imagem
salva, isolamento entre usuários. `tests/test_weekly_report_pdf_rendering.py`
(novo, unitário): PDF real com e sem imagem embutida, prova que o Pillow
realmente resolve o problema (não só por leitura de código). Suíte
completa rodada (92% de cobertura, gate de 85% ok).

## Consequências

- Container `api` fica um pouco maior (Pillow é uma wheel simples, sem
  libs de sistema como GDAL) — aceitável dado que o PDF é sempre ativo.
- Mais uma tabela pequena crescendo (uma linha por talhão elegível, nunca
  por ciclo) — sem risco de acúmulo sem controle.
- Cada ciclo de NDVI agora faz duas chamadas à Sentinel Hub por talhão
  (Statistical + Process) em vez de uma — mais consumo de cota, aceitável
  dado o ciclo já ser de 8h em 8h, não por request.
