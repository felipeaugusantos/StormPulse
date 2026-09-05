# ADR-0083 — Fase 5: satélite e inteligência do talhão

- **Status:** aceita e implementada
- **Data:** 2026-09-05

## Contexto

O módulo anterior guardava apenas a média e a imagem NDVI mais recente. Não
era possível avaliar tendência, qualidade, comparar datas ou distinguir uma
queda real de uma cena encoberta por nuvens.

## Decisão

O pipeline Sentinel-2 passa a coletar, em uma única consulta Statistical API,
NDVI, NDRE, EVI, NDMI e NDWI para todas as aquisições dos últimos 365 dias.
Cada observação guarda fonte, data, percentual válido, cobertura de
nuvens/sem dado, qualidade, confiabilidade e distribuição em zonas de vigor.

- Qualidade alta: pelo menos 80% de pixels válidos.
- Qualidade média: pelo menos 60%.
- Abaixo de 60%: baixa e não confiável. O valor pode ser exibido com aviso,
  mas não participa de comparação, anomalia ou alerta.
- Anomalia exige ao menos cinco observações históricas confiáveis anteriores.
- Queda persistente exige três observações confiáveis estritamente
  decrescentes e queda absoluta acumulada de pelo menos 0,08.
- A ausência de pixels válidos não cria leitura, imagem ou valor substituto.
- Estatística e imagem recebem o GeoJSON completo do talhão, não apenas seu
  centro ou bounding box. O bounding box serve somente para dimensionar a
  resolução do raster; `bounds.geometry` continua sendo o polígono original.

Imagens passam a ser históricas por `(location_id, index_name, observed_at)`.
A API oferece série em JSON, exportação CSV, mapa PNG com metadados em headers
e comparação das duas aquisições confiáveis mais recentes. Web mostra série,
zonas e imagens lado a lado; mobile mostra o resumo dos cinco índices.

## `boundary_geojson` versus PostGIS

A migração para `Geography(POLYGON, 4326)` foi avaliada e **adiada**. Hoje o
banco não executa interseção, distância ou agregação espacial sobre o
contorno: ele apenas persiste o polígono validado e o envia integralmente ao
Sentinel Hub. Converter agora criaria uma segunda representação ou exigiria
uma migração de contrato web/mobile sem benefício operacional imediato.

A migração torna-se indicada quando existir ao menos uma destas necessidades:

1. consulta espacial de talhões no banco;
2. interseção com mapas de solo, risco ou cobertura;
3. validação topológica avançada e reparo por `ST_MakeValid`;
4. simplificação/reprojeção server-side;
5. eliminação planejada do campo textual em favor de GeoJSON derivado com
   `ST_AsGeoJSON`.

Quando isso ocorrer, o caminho será adicionar `boundary_geom` em paralelo,
preencher com `ST_SetSRID(ST_GeomFromGeoJSON(boundary_geojson), 4326)`, validar
paridade, mudar leituras e somente depois remover o texto. Não haverá troca
destrutiva em uma única implantação.

## Consequências

O histórico de imagens aumenta o armazenamento. Em compensação, permite
comparação auditável e mantém a aquisição original associada à sua qualidade.
O mock continua disponível apenas em desenvolvimento e permanece marcado
explicitamente como simulado.
