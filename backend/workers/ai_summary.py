"""AI-generated natural-language summary of an already-computed storm risk
(FASE 9, ADR-0060).

Never a second source of risk prediction — the prompt only ever contains
numbers the deterministic `StormRiskEngine` already computed (severity,
per-hazard scores, distance/speed/ETA); Claude's only job is to phrase
those numbers as a short sentence, never to invent a value that isn't in
the prompt. Optional (`ANTHROPIC_API_KEY` unset → skipped, mirrors how
VAPID/SES degrade elsewhere in this app) and never raises — a bad response
or API outage must never break the ingestion cycle that triggered it.
"""

from __future__ import annotations

import logging

import anthropic

from app.core.config import Settings
from app.storms.models import StormRisk

logger = logging.getLogger(__name__)

# Fixed, not configurable — a short deterministic rephrasing of numbers
# already computed doesn't need (or justify the cost of) a bigger model.
_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 200

_SYSTEM_PROMPT = (
    "Você resume, em português do Brasil e em no máximo duas frases curtas, "
    "uma avaliação de risco de tempestade que um motor de regras já "
    "calculou. Use SOMENTE os números fornecidos na mensagem — nunca "
    "invente distância, velocidade, horário de chegada ou qualquer dado "
    "que não esteja explicitamente ali. Diga qual é o maior risco e por "
    "quê, de forma direta. Sem saudação, sem aviso legal, sem markdown."
)


def _build_prompt(risk: StormRisk) -> str:
    hazards = {
        "chuva": risk.rain_risk,
        "vento": risk.wind_risk,
        "granizo": risk.hail_risk,
        "raio": risk.lightning_risk,
    }
    top_hazard, top_score = max(hazards.items(), key=lambda item: item[1])
    lines = [
        f"Nível geral: {risk.severity.value}",
        f"Maior risco: {top_hazard} ({top_score:.0%})",
        "Todos os riscos: " + ", ".join(f"{name} {score:.0%}" for name, score in hazards.items()),
    ]
    if risk.storm_distance_km is not None:
        lines.append(f"Distância da célula: {risk.storm_distance_km:.0f} km")
    if risk.storm_speed_kmh is not None:
        lines.append(f"Velocidade de deslocamento: {risk.storm_speed_kmh:.0f} km/h")
    if risk.eta_minutes is not None:
        lines.append(f"Chegada estimada: {risk.eta_minutes} minutos")
    return "\n".join(lines)


def generate_summary(risk: StormRisk, settings: Settings) -> str | None:
    """Returns a short natural-language summary, or `None` if unconfigured
    or the API call itself fails."""
    if settings.anthropic_api_key is None:
        return None

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(risk)}],
        )
    except anthropic.APIError:
        logger.exception("Failed to generate AI risk summary", extra={"risk_id": str(risk.id)})
        return None

    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return None
