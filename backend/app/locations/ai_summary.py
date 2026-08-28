"""AI-generated natural-language reading of an already-built weekly
report (item "melhorar relatório").

Same discipline as `workers/ai_summary.py` (StormRisk's AI summary,
ADR-0060): Claude only ever rephrases numbers this same request already
computed — rainfall, dry days, area, alerts, NDVI — never a second source
of those numbers, never invents anything not in the prompt. Optional
(`ANTHROPIC_API_KEY` unset → skipped) and never raises — a bad response or
API outage must never break the report endpoint that triggered it. Async
(unlike the worker's sync client) because this runs inline in a FastAPI
request handler, not a Celery task — an `AsyncAnthropic` call here can be
awaited alongside the rest of the request instead of blocking the loop.
"""

from __future__ import annotations

import logging

import anthropic

from app.core.config import Settings
from app.locations.schemas import WeeklyReportOut

logger = logging.getLogger(__name__)

# Fixed, not configurable — same reasoning as the storm-risk summary: a
# short rephrasing of numbers already computed doesn't need a bigger model.
_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 250

_SYSTEM_PROMPT = (
    "Você é um agrônomo escrevendo, em português do Brasil e em no máximo "
    "três frases curtas, uma leitura objetiva do relatório semanal de um "
    "talhão. Use SOMENTE os números fornecidos na mensagem — nunca invente "
    "chuva, área, NDVI ou qualquer dado que não esteja explicitamente ali. "
    "Se não houver alerta ou leitura de NDVI no período, diga isso "
    "diretamente em vez de silenciar. Direto ao ponto, sem saudação, sem "
    "aviso legal, sem markdown."
)


def _build_prompt(report: WeeklyReportOut) -> str:
    lines = [
        f"Talhão: {report.location_name}",
        f"Cultura: {report.crop or 'não informada'}",
        f"Área: {report.area_ha:.2f} ha" if report.area_ha is not None else "Área: não informada",
        f"Período: {report.period_start.isoformat()} a {report.period_end.isoformat()}",
        f"Chuva acumulada no período: {report.rainfall_total_mm:.1f} mm",
        f"Dias secos no período: {report.dry_days_count}/7",
    ]
    if report.alerts:
        lines.append(
            "Alertas no período: "
            + "; ".join(f"{a.title} ({a.created_at.date().isoformat()})" for a in report.alerts)
        )
    else:
        lines.append("Alertas no período: nenhum")
    if report.ndvi_readings:
        lines.append(
            "Leituras de NDVI no período: "
            + "; ".join(
                f"{n.ndvi_mean:.2f} em {n.observed_at.date().isoformat()}"
                for n in report.ndvi_readings
            )
        )
    else:
        lines.append("Leituras de NDVI no período: nenhuma")
    return "\n".join(lines)


async def generate_report_summary(report: WeeklyReportOut, settings: Settings) -> str | None:
    """Returns a short natural-language reading of `report`, or `None` if
    unconfigured or the API call itself fails."""
    if settings.anthropic_api_key is None:
        return None

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(report)}],
        )
    except anthropic.APIError:
        logger.exception(
            "Failed to generate AI weekly-report summary",
            extra={"location_id": str(report.location_id)},
        )
        return None

    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return None
