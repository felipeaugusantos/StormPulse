# ADR-0076 — Imagem de satélite colorida (IR realçado) e temperatura visível

- **Status:** Aceito
- **Data:** 2026-08-29

## Contexto

Pergunta direta: "teria como mostrar no mapa o sensor de temperatura das
nuvens?". Investigação mostrou que o dado já existe e já é usado — o
satélite GOES-19 mede a temperatura do topo das nuvens (infravermelho,
banda 13) e isso já alimenta a detecção de "observação via satélite"
(`ConvectiveWatch.min_brightness_temp_k`) — mas de duas formas
incompletas:

1. A imagem renderizada no mapa (`SatelliteImage`) é puro **cinza** —
   sem nenhuma cor, difícil de ler visualmente onde está mais frio/
   perigoso.
2. Cada observação individual só mostra um rótulo categórico (fraca/
   moderada/forte/severa) — o **número da temperatura nunca aparecia em
   lugar nenhum**, nem na lista nem no mapa.

## Decisão

### Imagem "IR realçado" — cor só na faixa que importa

`_render_ir_image` (`workers/satellite_pipeline.py`) ganhou uma rampa de
cor (verde→amarelo→laranja→vermelho→magenta, mais frio = mais cor)
aplicada **só** abaixo de 228,15 K (-45°C, o mesmo limiar de "moderada"
já usado por `convectiveIntensity` no frontend) — acima disso (a grande
maioria de qualquer imagem real: céu comum, nuvem não-convectiva)
continua exatamente cinza, sem nenhuma mudança visual. Colorir a imagem
inteira teria pintado oceano e céu comum de verde sem necessidade —
produtos meteorológicos reais de IR realçado seguem a mesma lógica
(cor só na faixa de interesse convectivo).

As âncoras de cor (228,15 K / 218,15 K / 208,15 K) são a conversão exata
dos cortes em Celsius já usados por `convectiveIntensity`
(`web/src/format.ts`: -45/-55/-65°C) — front e back concordam sobre o
que "severa" significa, sem duplicar um número mágico novo.

### Temperatura real visível na lista de observações

`SatelliteWatchRow.tsx` agora mostra `-XX°C no topo` ao lado do rótulo
categórico — o dado (`min_brightness_temp_k`) já vinha na resposta da
API, só não era exibido em lugar nenhum.

### Legenda do mapa explica a nova escala

Um texto curto aparece na legenda quando a camada de satélite está
ativa, explicando a direção da escala de cor — sem isso, a mudança visual
não seria autoexplicativa pra quem nunca viu imagem de IR realçado antes.

## Verificação

`tests/test_satellite_image_render.py` (reescrito): pixels acima do
limiar continuam puro cinza (R=G=B, idêntico ao comportamento anterior);
as quatro âncoras da rampa renderizam exatamente as cores documentadas;
interpolação entre âncoras é suave (nunca pula direto de uma cor pra
outra); valores extremos (mais frio que a âncora mais fria, mais quente
que o teto) recortam pra cor/preto fixos em vez de estourar o intervalo.
Verificado visualmente no navegador local: observação de teste inserida
direto no banco (pipeline real de satélite exige GDAL/TATHU, não viável
rodar localmente) mostrando "-65°C no topo" na lista e a legenda
explicando a escala ao ativar a camada. Suíte completa rodada (92,98% de
cobertura, gate de 85% ok).

## Consequências

- Nenhum dado novo, nenhum custo — só reaproveitamento de um valor que já
  existia (`min_brightness_temp_k`) e uma mudança de renderização de uma
  imagem que já era gerada.
- A rampa de cor é uma escolha visual (não uma convenção internacional
  única — existem várias paletas de "IR realçado" na meteorologia), mas
  segue o mesmo espírito: quanto mais fria a nuvem, mais a cor "berra".
