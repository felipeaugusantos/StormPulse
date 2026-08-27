# ADR-0069 — Janela de plantio oficial (ZARC/MAPA) por talhão

- **Status:** Aceito
- **Data:** 2026-08-27

## Contexto

Análise do repositório externo `DeHor-Labs/mcp-agro-brasil` (agregador de
dados do agronegócio brasileiro via MCP) identificou um dado genuinamente
relevante para o StormPulse: o Zoneamento Agrícola de Risco Climático
(ZARC), publicado pelo MAPA — para cada (município, cultura, ciclo de
cultivar, tipo de solo), define quais decêndios (períodos de 10 dias) do
ano são recomendados para plantio, e com qual faixa de risco climático
oficial (20/30/40%).

O resto do que o repositório expõe (cotações de commodities, câmbio,
exportações) foi descartado por não ter relação com o produto — StormPulse
é clima/risco, não uma ferramenta de mercado agrícola.

## Investigação: não existe API do ZARC

Antes de decidir como consumir, foi confirmado que o próprio dataset do
MAPA (`dados.agricultura.gov.br`, "Tábua de Risco - Zoneamento Agrícola de
Risco Climático") **não tem API de consulta** — inspecionado via
`package_show` do CKAN, nenhum recurso tem `datastore_active`. É só um CSV
estático publicado por safra, `;`-delimitado, com 36 colunas `dec1..dec36`
(uma por decêndio) e um dicionário de dados oficial em PDF descrevendo os
códigos (`Cod_Ciclo`, `Cod_Solo`, etc.). A decisão, portanto, não é
"chamar uma API" — é ingerir o CSV publicado, do jeito que ele é
publicado, sem depender do MCP externo.

## Decisão

### Ingestão: tabela de referência global, replace completo

Novo `app.zarc.models.ZarcRiskWindow` — mesma categoria de
`WeatherSource`/`RadarFrame`: dado de referência global, sem
`TenantMixin`, sem RLS. Novo `workers/zarc_pipeline.py`
(`run_zarc_ingestion_cycle`) faz *delete-then-insert* completo da tabela
a cada ciclo: é dado de referência sem FK apontando pra linhas
individuais, e as próprias portarias oficiais da safra ocasionalmente são
emendadas/substituídas — uma linha antiga nunca deve conviver com sua
substituta. Roda semanalmente (`ZARC_ENABLED`, cadência própria em
`celery_app.py`) — mais frequente que isso só re-baixaria o mesmo arquivo
estático sem ganho.

### Resolução de município: reaproveitando a técnica já existente

O CSV do MAPA indexa por `geocodigo` do IBGE, não por lat/lon. Em vez de
inventar um segundo geocodificador, `app.zarc.geocode.resolve_municipio_geocode`
reaproveita exatamente a técnica já usada em
`app.weather.inmet.InmetWeatherProvider`: estação automática do INMET mais
próxima → UF/nome da estação → *match* exato (normalizado) contra a lista
pública de municípios do IBGE para aquela UF. Nenhum geocodificador de
terceiros envolvido.

### Consulta por talhão: nova propriedade, sem nova infraestrutura de campo

`Location` ganha `soil_type` (`arenoso`/`textura_media`/`argiloso` — as
três classes texturais principais do dicionário de dados; as classes
especializadas AD1-AD6 de capacidade de água não são oferecidas, pra
manter o seletor simples). Novo
`app.locations.zarc_service.get_zarc_window`: resolve o geocódigo do
talhão, mapeia `soil_type` → `Cod_Solo`, busca linhas de
`ZarcRiskWindow` por geocódigo+solo, e filtra em Python por
correspondência (normalizada, case/acento-insensível) do `crop` livre do
talhão contra a `cultura` de cada linha — sem forçar um vocabulário fechado
de culturas no talhão, que já é texto livre desde a FASE 26.

Novo endpoint `GET /locations/{id}/agro/zarc-window`, escopo talhão-only
(mesmo padrão 404 de NDVI/relatório semanal — um ponto de fazenda não tem
cultura/solo próprios pra consultar).

### Puramente informativo

Não existe campo de data de plantio no sistema hoje — o card
"🌱 Janela de Plantio (ZARC)" no dashboard mostra as janelas oficiais
(cultura, ciclo, safra, portaria, os 36 decêndios) para o talhão, mas não
gera alerta nem compara contra nada. Se um campo de data de plantio for
adicionado no futuro, comparar contra a janela oficial pra gerar um alerta
real é a evolução natural — deliberadamente fora de escopo aqui.

## Verificação

`tests/test_zarc_pipeline.py` (rede falsa via `httpx.MockTransport`):
parsing de linha do CSV, linha totalmente zerada é descartada, replace
completo entre ciclos. `tests/test_zarc_geocode.py`: resolução do
geocódigo pela estação mais próxima, ausência de estação/município
correspondente, falha de rede embrulhada em `MunicipioNotResolvedError`
em vez de vazar a exceção crua do `httpx`.
`tests/test_integration_zarc_window.py` (Postgres real, resolvedor de
geocódigo trocado por um fake — nunca uma chamada de rede real ao
INMET/IBGE nos testes): 404 pra fazenda, 404 pra talhão sem
cultura/solo, 404 quando nenhuma linha bate com a cultura, retorno
correto filtrando por solo. Suíte completa (ruff/mypy/pytest,
92% de cobertura) rodada contra Postgres/Redis reais.

Verificado também manualmente: migrações aplicadas contra o Postgres
local, backend rodando de verdade, e o fluxo completo no navegador —
cadastro de usuário, criação de fazenda+talhão com cultura e tipo de solo
pelo seletor novo, card "Janela de Plantio (ZARC)" aparecendo só depois
de cultura+solo preenchidos. Neste ambiente sem acesso de rede real ao
INMET, a chamada de geocodificação falha e o endpoint responde 404 de
forma limpa — descoberto durante a própria verificação manual e corrigido
(a falha de rede crua do `httpx` não era capturada antes, resultando em
500).

## Consequências

- Puramente aditivo — nenhum contrato/endpoint existente muda.
- Mais uma tabela de referência global crescendo (~centenas de milhares
  de linhas por safra, esperado), substituída por completo a cada ciclo
  semanal — sem acúmulo sem controle.
- Depende da disponibilidade do INMET/IBGE no momento da consulta (a
  resolução de geocódigo é *on-demand*, não cacheada) — uma falha
  temporária de rede vira 404 honesto, não um erro fabricado nem um dado
  aproximado.
