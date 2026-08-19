# Storm Engine

Motor meteorológico **determinístico** e desacoplado de qualquer fonte.

Submódulos:

- `geo.py` — geometria great-circle (haversine, bearing, projeção). ✅
- `config.py` — thresholds centralizados (sem números mágicos). ✅
- `provider_types.py` — entradas desacopladas (`FrameInput`/`RawCellInput`). ✅
- `detection/` — detecção de células + severidade determinística. ✅ (FASE 6)
- `tracking/` — associação temporal por vizinho mais próximo. ✅ (FASE 7)
- `trajectory/` — deslocamento, direção, velocidade, tendência, ETA. ✅ (FASE 7)
- `pipeline.py` — fachada detecção→tracking→trajetória. ✅
- `risk/` — `StormRiskEngine` por regras documentadas (ADR-0005). ✅ (FASE 8)
- `ingestion/` 🔭 — normalização de fontes — FASE 13.
- `forecasting/` 🔭 — projeção de curto prazo.

> Regra: LLMs **não** classificam severidade. Algoritmos experimentais e dados
> simulados devem ser marcados explicitamente (`experimental` / `MOCK`).
