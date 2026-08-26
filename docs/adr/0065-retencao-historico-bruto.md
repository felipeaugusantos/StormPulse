# ADR-0065 — Retenção do histórico bruto dos providers (item 4 do Radar Competitivo)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Quarto item da sequência priorizada. `workers/pipeline_service.py` já
buscava `provider.get_radar_frames()` a cada ciclo de ingestão, mas só
persistia a saída *derivada*: depois do `StormEngine` agrupar/rastrear as
células cruas em `StormCell`/`StormTrack`/`StormObservation`, a lista
bruta de células que o provider realmente devolveu naquele ciclo
(`RawCell`: lat/lon/refletividade/área, antes de qualquer agrupamento)
era descartada — nunca gravada em lugar nenhum.

## O que já existia, sem uso

`app.weather.models.RadarFrame`/`WeatherSource` já existiam desde o
bootstrap do schema (FASES 2-5) — arquitetura preparada exatamente para
isto, mas nunca conectada a nenhum código de escrita (confirmado via
busca: zero referências fora do próprio módulo e do registro em
`app/models.py`). Mesma categoria de "arquitetura preparada, não
plugada" que `UserReport` (FASE 16).

## Decisão

### Persistir antes do engine consumir

Em `run_ingestion_cycle`, logo após buscar os frames e **antes** de
`StormEngine().process(...)` transformá-los, cada `RadarFrameData` vira
uma linha `RadarFrame` (`captured_at`, `is_mock`, e `meta` JSONB com a
lista crua de células + nome da fonte). Um `WeatherSource` é
obtido-ou-criado por nome do provider (`_get_or_create_weather_source`)
— nunca duplicado entre ciclos, já que o nome é único.

### Poda automática, mesma disciplina do resto do pipeline

Sem limite, uma tabela alimentada a cada 5 minutos cresceria
indefinidamente. Nova configuração `RAW_FRAME_RETENTION_DAYS` (default
30 dias) + `_prune_old_raw_frames`, mesmo padrão de
`_prune_old_mock_cells` já existente no mesmo arquivo.

### Exposto, não só gravado

"Reter" sem conseguir consultar não é muito útil — novo endpoint
`GET /admin/raw-frames` (operador da plataforma, cross-tenant, mesmo
padrão de `/admin/audit-log`) lista o histórico paginado. Nova aba
"Histórico bruto" no `AdminPanel.tsx` do frontend (mesmo padrão visual
das abas Auditoria/Pipelines já existentes) — mostra fonte, contagem de
células brutas e timestamp de cada quadro retido.

## Verificação

`tests/test_raw_frame_retention.py` (3 testes, Postgres real): ciclo de
ingestão persiste um `RadarFrame` com a lista de células no `meta`;
`WeatherSource` é reusado (não duplicado) entre ciclos; um quadro antigo
além da janela de retenção é removido no ciclo seguinte.
`tests/test_integration_admin.py` (+2 testes): 403 para não-operador,
listagem retorna o histórico persistido com paginação. Verificado também
manualmente contra o banco real (`docker compose` local): rodado
`run_ingestion_cycle` diretamente, confirmado a contagem de `RadarFrame`
subir e o `meta` conter a célula bruta exata que o `MockWeatherProvider`
devolveu — e no browser, a aba "Histórico bruto" do painel admin
mostrando 36 quadros retidos de execuções reais anteriores desta sessão,
com badge MOCK/real, fonte e timestamp corretos.

## Consequências

- Puramente aditivo — nenhum contrato/endpoint existente muda; a saída
  derivada (`StormCell` etc.) continua exatamente como era.
- Uma tabela a mais crescendo em produção, mas com poda automática
  configurável — não é um passivo de armazenamento sem controle.
- Escopo desta fase é o radar (a única fonte cujo ciclo de ingestão
  descartava o dado bruto sistematicamente); raios já gravam cada
  detecção individual (`LightningStrike`) e NDVI/satélite já gravam a
  própria leitura/observação — nenhum gap equivalente encontrado ali.
