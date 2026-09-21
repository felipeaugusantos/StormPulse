# ADR-0091 — Fase 8: Visualização de satélite em tempo real

- **Status:** Aceito
- **Data:** 2026-09-20

## Contexto

Você perguntou se dava pra implementar algo parecido com o visualizador de
satélite do weathernerds.org (loop animado de IR do GOES-East, raios,
avisos oficiais e rodovias sobre o mesmo mapa). Diagnóstico mostrou que a
maior parte já existia — ingestão GOES-19 banda 13 via INPE STAC, rampa
de cor "enhanced IR", retenção de histórico (`SatelliteImage`, FASE 16/18,
ADR-0009/0013/0076) — inclusive um scrubber de animação já implementado,
mas só dentro do `Dashboard.tsx` autenticado (`buildSatelliteTimeline`/
`timelinePlaying`), nunca extraído pra reuso.

Faltava de fato: (1) o mesmo scrubber na visão pública (`VisitorView.tsx`)
e no mobile, que só mostravam o frame mais recente; (2) uma camada de
avisos ativos no mapa — `Alert` existe e é ligado a um `location_id`, mas
nunca foi desenhado como camada, só em lista; (3) uma camada de rodovias
— não existe fonte de dados de malha rodoviária no projeto.

## Decisões

**Rodovias ficaram fora do escopo.** Investigado: DNIT tem malha oficial
(SNV) mas só exporta PDF/XLS/CSV no portal de dados abertos (sem GeoJSON
direto). O IBGE tem o dado geoespacial real (BC250, sistema viário, malha
oficial) em `geoftp.ibge.gov.br`, mas como um único ZIP de ~769MB
cobrindo o Brasil inteiro (todas as camadas cartográficas juntas, não só
rodovias) — processar isso (baixar, filtrar rodovias federais, simplificar
geometria, converter pra GeoJSON) é um trabalho de engenharia de dados
à parte, não algo pra encaixar dentro desta fase sem inflar demais o
escopo. Não inventada nenhuma coordenada como substituto — a camada
simplesmente não foi construída. Fica como trabalho futuro, com a fonte
já identificada e verificada.

**Scrubber extraído para `useSatelliteTimeline` (hook) +
`SatelliteTimelineBar` (componente), reaproveitado por `Dashboard` e
`VisitorView`.** A lógica de construção da linha do tempo
(`buildSatelliteTimeline`/`stormsForTimelineStep`, `stormTimeline.ts`) já
era pura e testada — o que faltava reaproveitar era o *estado* (índice,
play/pause, avanço automático) e a *UI* (botão + slider), ambos
implementados só dentro do `Dashboard.tsx`. Extração pura, sem mudar o
comportamento existente (mesmos testes, mesmo timing de 900ms por
quadro).

**`VisitorView` (público) passa a buscar `/public/satellite/images`
(histórico), que já existia na API mas nunca era consumido pelo
frontend** — só a imagem mais recente. Nenhuma mudança de backend.

**Mobile ganha sua primeira infraestrutura de scrubber** — porta de
`stormTimeline.ts`/`useSatelliteTimeline.ts` (mesmo padrão de "porte"
já usado pra `storm.ts`/CAPE), um componente `SatelliteTimelineBar.tsx`
próprio usando `@react-native-community/slider` (nova dependência —
`react-native` não tem um `<input type=range>` nativo) no lugar do
`<input type="range">` do web. `mobile/src/api.ts`'s
`satelliteImagePngUrl` ganhou o parâmetro `imageId` que o web já tinha
(sem ele, o scrubber mobile sempre mostraria o frame mais recente,
nunca um frame histórico de verdade — o endpoint `/public/satellite/
image.png` sempre serve o mais recente; `/public/satellite/images/
{id}.png` é quem serve um frame específico).

**`StormCell` do mobile ganhou os campos de projeção
(`speed_kmh`/`direction_deg`/`projected_latitude_1h`/
`projected_longitude_1h`)** — já existiam no schema real do backend
(`app/storms/schemas.py`) e no tipo web, só nunca tinham sido portados
pro tipo mobile. Sem eles, `stormsForTimelineStep` não teria como
interpolar a posição projetada em +1h no mobile. Não desenha a marca
"fantasma" da projeção no `StormMapView.tsx` (esse é só o dado — a UI
de projeção em si fica fora do escopo desta fase).

**Camada de avisos ativos: um anel colorido por `RiskLevel` ao redor do
ponto do talhão, em vez de uma área poligonal.** `Alert` não carrega
geometria própria (nunca foi um "warning polygon" como o dos EUA), só
`location_id` — a implementação junta `alerts` (já buscado tanto no
`Dashboard` quanto no `HomeScreen`) contra `locations` (que tem lat/lon)
inteiramente no cliente, sem endpoint novo. Web: `StormMap.tsx` ganha um
`circle`-layer MapLibre extra (`active-alerts`), raio fixo, cor por
`RiskLevel`. Mobile: `StormMapView.tsx` ganha um `Circle` do
`react-native-maps` no mesmo espírito. `VisitorView` não ganhou essa
camada — visitante não tem tenant/alertas próprios, não haveria o que
desenhar.

## Consequências

- Nenhuma migração, nenhum endpoint novo — tudo reaproveitando dado e
  API já existentes.
- Nova dependência mobile: `@react-native-community/slider`.
- `web/src/components/Dashboard.tsx` teve sua lógica de timeline
  extraída sem mudar comportamento (mesmos testes de
  `stormTimeline.test.ts` continuam valendo; `useSatelliteTimeline.ts`
  ganhou testes próprios de estado/play-pause).
- Verificação visual ao vivo no navegador não foi feita nesta fase — um
  container de outro projeto do usuário já ocupava a porta 5432 local no
  momento da implementação, impedindo subir o Postgres do StormPulse
  sem mexer em infraestrutura de outro projeto. Cobertura por testes
  automatizados (typecheck limpo, 100 testes web + 36 testes mobile,
  incluindo os novos de `useSatelliteTimeline`/`stormTimeline`) e pela
  própria CI (que sobe Postgres/Redis isolados) substituem essa
  verificação — mas o próximo passo recomendado é abrir o Dashboard e o
  app mobile uma vez, manualmente, pra conferir visualmente antes de
  considerar a fase 100% fechada.
- Camada de rodovias explicitamente adiada — fonte de dados real
  identificada (IBGE BC250, `geoftp.ibge.gov.br`) mas processá-la
  (filtrar rodovias federais de um ZIP de ~769MB, simplificar, converter
  pra GeoJSON) é trabalho de engenharia de dados que fica para uma fase
  futura, se o dono do produto decidir que vale a pena.
