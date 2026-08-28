"""Unit tests for the weekly-report AI summary module (item "melhorar
relatório").

Same mocking pattern as `test_ai_summary.py` (StormRisk's AI summary) —
`anthropic.AsyncAnthropic` itself is monkeypatched, no real API call ever
happens. No Postgres/Redis needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2

from app.core.config import Settings
from app.locations.ai_summary import generate_report_summary
from app.locations.schemas import WeeklyReportOut


def _report(**overrides: Any) -> WeeklyReportOut:
    base: dict[str, Any] = {
        "location_id": uuid.uuid4(),
        "location_name": "Talhão Soja",
        "crop": "soja",
        "area_ha": 12.34,
        "period_start": date(2026, 8, 21),
        "period_end": date(2026, 8, 27),
        "rainfall_total_mm": 15.5,
        "dry_days_count": 4,
        "alerts": [],
        "ndvi_readings": [],
        "generated_at": datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return WeeklyReportOut(**base)


async def test_returns_none_when_unconfigured() -> None:
    settings = Settings(environment="test", anthropic_api_key=None)
    assert await generate_report_summary(_report(), settings) is None


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


async def test_returns_the_generated_text_on_success(monkeypatch: Any) -> None:
    fake_response = SimpleNamespace(
        content=[_FakeTextBlock("Chuva moderada, sem alertas relevantes no período.")]
    )
    fake_messages = _FakeMessages(response=fake_response)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = await generate_report_summary(_report(), settings)

    assert result == "Chuva moderada, sem alertas relevantes no período."
    # The prompt is built only from the report's own real numbers — never
    # a placeholder/fabricated value.
    prompt = fake_messages.calls[0]["messages"][0]["content"]
    assert "12.34 ha" in prompt
    assert "15.5 mm" in prompt
    assert "4/7" in prompt
    assert "nenhum" in prompt.lower()


async def test_returns_none_on_api_error(monkeypatch: Any) -> None:
    fake_request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_messages = _FakeMessages(error=anthropic.APIConnectionError(request=fake_request))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = await generate_report_summary(_report(), settings)

    assert result is None


async def test_returns_none_when_response_has_no_text_block(monkeypatch: Any) -> None:
    fake_response = SimpleNamespace(content=[])
    fake_messages = _FakeMessages(response=fake_response)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = await generate_report_summary(_report(), settings)

    assert result is None
