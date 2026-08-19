# ADR-0004 — MapLibre para mapas (não Mapbox por padrão)

- **Status:** Aceito
- **Data:** 2026-08-19
- **Contexto:** FASE 0 (uso nas FASES 11/12)

## Contexto

Dashboard admin e app mobile precisam renderizar mapas com células de
tempestade, trajetórias e raios de monitoramento.

## Opções consideradas

1. **MapLibre GL** (open source, fork do Mapbox GL JS pré-licença proprietária).
2. **Mapbox GL** (comercial, requer token e tem custo por uso).

## Decisão

Adotar **MapLibre GL** (`maplibre-gl` no web, `@maplibre/maplibre-react-native`
no mobile) como padrão.

## Justificativa

- **Open source e sem lock-in:** sem token obrigatório nem cobrança por
  carregamento de mapa; podemos usar tiles de provedores variados ou próprios.
- **API compatível** com o ecossistema Mapbox GL, então migrar depois é barato.
- Recursos necessários (camadas GeoJSON para células/trajetórias, círculos de
  raio, animação de frames) são plenamente suportados.

### Quando reavaliar Mapbox

Somente se surgir uma vantagem justificável e específica (ex.: um recurso de
tiles/routing proprietário que precisemos e que o ecossistema MapLibre não
cubra). Até lá, Mapbox adicionaria custo e dependência sem retorno claro.

## Consequências

- Precisamos definir uma fonte de tiles (ex.: provedor gratuito/aberto ou
  self-host) na FASE 11 — decisão separada.
