# ADR-0022 — Talhão: sub-local dentro da fazenda

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 26 — usuário perguntou se o sistema tinha talhões; escolheu a opção mais simples entre as duas propostas

## Contexto

O sistema não tinha nenhum conceito de talhão — cada `Location` era um
ponto único, então uma fazenda com várias áreas de cultivo precisava de um
local por área, sem relação entre eles. Duas abordagens foram propostas:
polígono real desenhado no mapa (fiel à realidade agrícola, mas exige nova
geometria PostGIS e UI de desenho) ou um sub-local simples (ponto com nome,
cultura e um local-pai). A segunda foi escolhida — reaproveita 100% da
lógica de clima/agro já existente (que é toda por `location_id`/lat-lon),
sem exigir nenhuma UI de mapa nova.

## Decisão

`Location` (`backend/app/locations/models.py`) ganhou dois campos:
`parent_location_id` (FK para `locations.id`, `ON DELETE CASCADE`,
nullable) e `crop` (string livre, nullable). Um talhão é só uma `Location`
com `parent_location_id` apontando pra sua fazenda.

**Regra de nesting**: só um nível — um talhão não pode ele mesmo ter
filhos. Validado no router (`_validate_parent`), não no banco (a FK por si
só permitiria uma árvore de qualquer profundidade) — mais simples que uma
constraint recursiva, e o caso de uso não precisa de mais de um nível.

**Escopo por tenant/usuário**: o pai precisa pertencer ao mesmo usuário
autenticado (mesma checagem de `_get_owned_or_404`), senão 404 — nunca 403,
mesmo padrão de todo o resto do isolamento por tenant neste projeto (não
revelar que o recurso existe).

**Nenhuma mudança nos endpoints de clima/agro** — `/forecast`,
`/agro/rain-forecast`, `/spray-window`, `/rainfall`, `/current` continuam
recebendo só `location_id`, então um talhão automaticamente tem clima,
geada, pulverização, trafegabilidade, CAPE, balanço hídrico, GDD, risco de
doença e VPD — tudo isso já filtra por local, nunca por "é uma fazenda ou
um talhão".

**Frontend**: `LocationSearchCard.tsx` agrupa a lista plana de locais em
fazendas (`parent_location_id == null`) com seus talhões aninhados
visualmente por baixo; botão "+ talhão" abre um formulário inline (nome,
cultura opcional, lat/lon pré-preenchidos com a coordenada da fazenda,
editáveis) — sem busca de cidade, um talhão nunca é um lugar novo pra
procurar.

## Consequências

- Migração nova (`f2a7c4e9b1d6`) só adiciona 2 colunas + 1 índice —
  retrocompatível, nenhum local existente muda de comportamento.
- Apagar uma fazenda apaga seus talhões em cascata (mesmo padrão de
  `ON DELETE CASCADE` usado em toda a base) — testado
  (`test_deleting_a_farm_cascades_to_its_plots`).
- Painéis de Agro no dashboard (`Dashboard.tsx`) já iteram sobre todos os
  locais ativos sem distinguir fazenda de talhão — um talhão aparece nos
  cards de geada/pulverização/trafegabilidade/etc. como qualquer outro
  local, com seu próprio nome e (quando presente) cultura.
