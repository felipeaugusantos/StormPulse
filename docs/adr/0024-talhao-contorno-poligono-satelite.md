# ADR-0024 — Contorno do talhão (polígono) e basemap de satélite real

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 27 — usuário pediu, depois do talhão simples (ADR-0022), pra desenhar a área real no mapa com imagem de satélite, colorida por cultura

## Contexto

O talhão (ADR-0022) foi implementado como ponto + cultura — decisão
deliberada pra reaproveitar toda a lógica de clima/agro sem precisar de
geometria. O usuário pediu, na sequência, pra completar isso com um
contorno visual real (polígono) sobre imagem de satélite, colorido por
cultura (milho de uma cor, cana de outra, café de outra). Perguntado se o
polígono deveria substituir o ponto ou conviver com ele, e se seria só web
ou também mobile — a resposta foi: **convivem** (ponto continua decidindo
clima; polígono é só visual) e **as duas plataformas**.

## Decisão

### Armazenamento: só visual, nunca usado pra clima

`Location.boundary_geojson` (Text, nullable) guarda um GeoJSON `Polygon`
serializado como string JSON. Nenhuma coluna PostGIS nova, nenhuma query
espacial contra ele — é puramente pra desenhar no mapa. `latitude`/
`longitude` continuam sendo o que todo endpoint de clima/agro usa, sem
nenhuma mudança. Validado no schema (`_validate_boundary_geojson`) só
quanto a ser um GeoJSON Polygon parseável com um anel de pelo menos 4
pontos (incluindo o de fechamento) — nunca quanto a auto-interseção ou
outras propriedades topológicas, que não importam pra um desenho.

### Cor por cultura

`web/src/cropColors.ts` (`cropColor(crop)`): paleta fixa pra culturas
comuns (soja, milho, cana, café, algodão, trigo, arroz, pastagem, feijão)
e um hash determinístico como fallback — a mesma cultura sempre recebe a
mesma cor, mesmo se não estiver na lista fixa. Puramente uma função do
nome da cultura, sem estado nem persistência de cor no banco.

### Web: desenho por clique, sem biblioteca nova

Em vez de adicionar `mapbox-gl-draw`/`terra-draw` (risco de compatibilidade
com MapLibre e mais uma dependência pesada no bundle, que já tem o aviso de
976KB), o desenho foi implementado direto em `StormMap.tsx`: um "modo de
desenho" (`startDrawing`/`finishDrawing`/`cancelDrawing` no
`StormMapHandle`) onde cada clique no mapa adiciona um vértice a uma fonte
GeoJSON de rascunho (linha tracejada + pontos), e "Concluir" fecha o anel.
O fluxo cruza dois componentes irmãos sob `Dashboard.tsx` (o mapa e o
formulário de talhão em `LocationSearchCard.tsx`) via uma callback
pendente guardada em ref (`pendingBoundaryCallbackRef`) — o formulário
pede pra desenhar, o Dashboard entra em modo de desenho, e quando o
usuário conclui, o polígono resultante é entregue de volta pro formulário
como uma string JSON pronta pra mandar no `boundary_geojson`.

### Basemap de satélite: Esri World Imagery, sem chave

Mesmo padrão de "grátis, sem chave" já usado no projeto (Open-Meteo,
Nominatim): `server.arcgisonline.com/.../World_Imagery/...` como uma
segunda fonte raster no estilo do MapLibre, alternável por um checkbox
("🛰️ imagem de satélite (mapa)") que troca a visibilidade entre essa e o
basemap OSM de ruas — sem recriar o mapa, só troca de camada.

### Mobile: implementado numa rodada seguinte

Adiado inicialmente (o app mobile não tinha nenhum componente de mapa
ainda), depois retomado: `react-native-maps` (`MapView`/`Polygon`,
`mapType="satellite"` nativo — sem tiles/chave, ao contrário do Esri do
web) numa tela nova, `mobile/src/screens/PlotBoundaryMapScreen.tsx` —
toque no mapa adiciona vértice, "Desfazer"/"Cancelar"/"Concluir" mesma
lógica do web, entregue de volta pra `LocationsScreen.tsx` como o mesmo
JSON string de `boundary_geojson`. Sem biblioteca de navegação: a tela
de mapa é uma troca de render condicional dentro de `LocationsScreen`,
mesmo padrão do resto do app.

Como o mobile não tem `<input type="color">`, a cor manual (ADR-0025)
virou uma paleta de swatches tocáveis (`COLOR_PALETTE`, novo export em
`cropColors.ts`) em vez do seletor nativo do navegador — mesma ideia,
adaptada à plataforma.

## Consequências

- Migração nova (`c7d29f4a8e1b`) só adiciona uma coluna nullable —
  retrocompatível, nenhum talhão existente (ponto-só) quebra.
- Nenhuma mudança na lógica de clima/agro — `boundary_geojson` nunca é lido
  por nenhum provider ou cálculo.
- Testes novos cobrem a validação do schema (JSON malformado, tipo errado,
  anel curto demais) e o roundtrip de criar um talhão com contorno.
