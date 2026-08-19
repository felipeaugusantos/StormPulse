# Storm Engine 🔭

Motor meteorológico **determinístico**. Placeholder de FASE 0/1 — implementado a
partir da FASE 6.

Submódulos planejados (cada um com interface + implementação inicial simples,
substituível):

- `ingestion/` — normaliza dados de `WeatherProvider` para o formato interno.
- `radar/` — processamento de frames de radar.
- `detection/` — detecção de `StormCell` em um frame.
- `tracking/` — associação temporal de células → `StormTrack`.
- `trajectory/` — deslocamento, direção, velocidade, ETA, projeção.
- `risk/` — `StormRiskEngine` (regras documentadas; ver ADR-0005).
- `forecasting/` — projeção de curto prazo.

> Regra: LLMs **não** classificam severidade. Algoritmos experimentais e dados
> simulados devem ser marcados explicitamente (`experimental` / `MOCK`).
