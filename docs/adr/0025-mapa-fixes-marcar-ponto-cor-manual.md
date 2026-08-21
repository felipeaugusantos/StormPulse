# ADR-0025 — Correção do mapa (zoom resetando), ocultar legenda, marcar ponto e cor manual do talhão

- **Status:** Aceito
- **Data:** 2026-08-21
- **Contexto:** FASE 27 (continuação) — feedback direto do usuário depois de usar o desenho de talhão (ADR-0024): o mapa resetava o zoom a cada 30s, pediu pra esconder a legenda, marcar um ponto no mapa pra um novo local, e não conseguia mudar a cor de uma cultura já criada

## Contexto

Quatro problemas relatados de uma vez, todos no `StormMap.tsx`/fluxo de
locais:

1. **Bug real**: `map.fitBounds(...)` rodava dentro do efeito que
   atualiza os dados do mapa — esse efeito reexecuta a cada
   `REFRESH_MS` (30s, todo o polling do dashboard), então qualquer zoom/
   pan manual do usuário era desfeito no próximo ciclo.
2. Pedido pra esconder a legenda do mapa (lista de cores fraca/moderada/
   forte/severa/etc.).
3. Pedido pra marcar um ponto no mapa (ex: a rua de casa) como forma
   alternativa de cadastrar um local, além da busca por cidade.
4. **Não é bug** (era falta de funcionalidade): a cor da cultura era só
   derivada automaticamente (`cropColor()`, ADR-0024) — não existia
   nenhum jeito de mudar manualmente a cor de um talhão já criado.

## Decisão

### 1. Zoom não reseta mais

`StormMap.tsx` ganha `hasFitBoundsRef` — o `fitBounds` só roda **uma vez**,
na primeira vez que há pontos pra mostrar, nunca de novo a cada polling.
Navegação pra um ponto específico (selecionar um local, clicar numa
observação de satélite ou raio) continua funcionando via `flyTo`,
independente disso.

### 2. Legenda ocultável

Um botão (`.legend-toggle`, "✕ legenda" / "☰ legenda") fica sempre visível
no canto superior-esquerdo do mapa — clicar esconde/mostra a barra de
legenda inteira (`showLegend`, estado no `Dashboard.tsx`).

### 3. Marcar ponto no mapa

Mesmo padrão de "callback pendente" já usado pro desenho de polígono
(ADR-0024), mas pra um clique só: `StormMapHandle.startPointPick(onPick)`
arma o próximo clique do mapa pra chamar `onPick(lat, lon)` uma vez e sair
do modo sozinho — sem precisar de "Concluir". Botão novo "🖊️ marcar no
mapa" ao lado de "usar minha localização" em `LocationSearchCard.tsx`,
que reaproveita o mesmo `pick()` já usado pela busca de cidade (com
geocodificação reversa pra um rótulo amigável).

### 4. Cor manual do talhão

`Location.color` (String(7), nullable, `#RRGGBB`) — um override que
substitui `cropColor(crop)` quando presente. Validado no schema
(`_validate_color`, regex hex) mesma disciplina do `boundary_geojson`.

Duas entradas na UI:
- **Ao criar um talhão**: um `<input type="color">` pré-preenchido com
  `cropColor(cultura)`, editável antes de salvar.
- **Num talhão já existente**: um swatch de cor inline na própria linha
  do talhão (`LocationSearchCard.tsx`), que já dispara
  `api.updateLocation(id, {color})` no `onChange` — essa era a lacuna
  relatada ("não consegui alterar").

`api.updateLocation` (novo em `web/src/api.ts`, PUT `/locations/{id}`) não
existia ainda no frontend apesar do backend já suportar — usado agora
tanto pra isso quanto disponível pra qualquer edição futura de local.

## Consequências

- Migração nova (`d4f8b2e6c9a3`) só adiciona uma coluna nullable —
  retrocompatível.
- `Dashboard.tsx`'s `plotBoundaries` agora usa `l.color ?? cropColor(l.crop)`
  — a derivação automática continua sendo o fallback, nunca removida.
- Testes novos cobrem criar com cor, rejeitar cor malformada, e atualizar
  a cor de um local existente via PUT.
