# ADR-0019 — Raios (descargas atmosféricas) via API-REDEMET STSC

- **Status:** Aceito
- **Data:** 2026-08-20
- **Contexto:** FASE 23 — análise da API-REDEMET (DECEA/Aeronáutica)

## Contexto

Você pediu pra analisar a [REDEMET](https://redemet.decea.mil.br) (Rede de
Meteorologia do Comando da Aeronáutica). Diferente do Agritempo (ADR-0018,
mapas por estado, sem API pública), a REDEMET tem uma
[API documentada](https://ajuda.decea.mil.br/base-de-conhecimento/api-redemet-o-que-e/)
com produtos reais em JSON: METAR/TAF/Aeródromos (clima pontual de
aeroporto), Produtos RADAR (eco de radar meteorológico brasileiro, imagem
georreferenciada), SIGMET (aviso oficial de tempestade em polígonos de FIR,
centenas de km), e **STSC** (ocorrência de descarga atmosférica/raio, ponto
a ponto, em tempo quase real).

Comparado aos dois: METAR/SIGMET não mapeiam bem pro nosso modelo de local
monitorado (aeroporto pontual ou polígono enorme demais), RADAR é
valioso mas é mais trabalho (imagem, mesmo padrão do satélite). STSC é o
sinal mais direto de convecção ativa que o sistema não tinha — diferente
de `StormCell` (taxa de chuva do INMET) e `ConvectiveWatch` (topo de nuvem
fria via satélite), ambos proxies indiretos, raio é detecção real do
fenômeno. Escolhido pra implementar primeiro (RADAR fica pra depois, se
quiser).

Exige cadastro gratuito (nome/e-mail/motivo de uso) — você já se cadastrou
e forneceu a chave.

## Decisão

- Nova tabela `lightning_strikes` (`app/lightning/models.py`) — global,
  sem `tenant_id` (mesmo motivo de `StormCell`/`ConvectiveWatch`: fenômeno
  físico, não dado por tenant). Só `detected_at`/`latitude`/`longitude`/
  `is_mock` — sem geometria PostGIS por enquanto (YAGNI: não há endpoint
  "raios próximos" ainda, só listagem pro mapa).
- `workers/lightning_pipeline.py`: busca `GET produtos/stsc` (header
  `X-Api-Key`, primeira opção de autenticação nos docs da DECEA) a cada
  ciclo, pega o quadro mais recente de `data.stsc` (a API devolve uma
  lista de quadros de animação — usamos só o último), grava os pontos, e
  **remove qualquer raio mais velho que `LIGHTNING_RETENTION_MINUTES`**
  (padrão 30min) — é um instantâneo do "agora", não histórico permanente,
  mesmo espírito do `SatelliteImage` (ADR-0009).
- `Settings.lightning_enabled` (padrão `false`) + `redemet_api_key` — sem
  chave configurada, o ciclo é um no-op honesto (log de aviso), nunca
  finge ter dado.
- Nova task Celery (`run_lightning_detection_task`), a cada 5 minutos —
  mesma cadência da ingestão principal, mais rápida que satélite (10min):
  raio é o sinal que muda mais rápido do sistema.
- Endpoints `GET /lightning` (autenticado) e `GET /public/lightning`
  (visitante) — mesmo padrão de `storms`/`satellite`.
- Frontend: `StormMap.tsx` ganha uma camada de pontos amarelos pequenos,
  desenhada por cima de tudo (célula, local, observação via satélite) —
  é o sinal mais urgente/instantâneo no mapa. Legenda mostra a contagem só
  quando há raios ativos.

## Consequências

- `httpx.Client` síncrono no worker (não async) — mesma escolha já feita
  em `satellite_pipeline.py`, pelo mesmo motivo: Celery é síncrono, e não
  existe (nem faz sentido forçar) uma abstração tipo `WeatherProvider` pra
  um produto que devolve uma lista de pontos nacional, não clima por
  coordenada.
- `parse_stsc_points` é função pura, testada isoladamente contra o
  formato real documentado pela DECEA (inclusive entradas malformadas —
  nunca quebra o ciclo por um ponto individual ruim).
- Sem RADAR nem SIGMET por enquanto — ficam como possível próxima fase se
  fizer sentido.
