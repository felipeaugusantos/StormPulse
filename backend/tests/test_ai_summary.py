"""Unit tests for the AI risk-summary module (FASE 9, ADR-0060).

No real Anthropic API call ever happens here — `anthropic.Anthropic` itself
is monkeypatched, mirroring how `boto3.client` is mocked in test_email.py.
No Postgres/Redis needed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx2

from app.core.config import Settings
from app.core.enums import RiskLevel
from app.storms.models import StormRisk
from workers.ai_summary import generate_summary


def _risk(**overrides: Any) -> StormRisk:
    # A SimpleNamespace duck-types fine for `generate_summary`, which only
    # reads plain attributes off the risk — cast so mypy sees the real
    # `StormRisk` type this stands in for.
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "severity": RiskLevel.RED,
        "rain_risk": 0.2,
        "wind_risk": 0.1,
        "hail_risk": 0.85,
        "lightning_risk": 0.3,
        "storm_distance_km": 12.0,
        "storm_speed_kmh": 30.0,
        "eta_minutes": 24,
    }
    base.update(overrides)
    return cast(StormRisk, SimpleNamespace(**base))


def test_returns_none_when_unconfigured() -> None:
    settings = Settings(environment="test", anthropic_api_key=None)
    assert generate_summary(_risk(), settings) is None


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


def test_returns_the_generated_text_on_success(monkeypatch: Any) -> None:
    fake_response = SimpleNamespace(content=[_FakeTextBlock("Risco alto de granizo em 24 min.")])
    fake_messages = _FakeMessages(response=fake_response)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = generate_summary(_risk(), settings)

    assert result == "Risco alto de granizo em 24 min."
    # The prompt is built only from the risk's own real numbers — never a
    # placeholder/fabricated value.
    prompt = fake_messages.calls[0]["messages"][0]["content"]
    assert "granizo 85%" in prompt
    assert "12 km" in prompt
    assert "24 minutos" in prompt


def test_returns_none_on_api_error(monkeypatch: Any) -> None:
    fake_request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_messages = _FakeMessages(error=anthropic.APIConnectionError(request=fake_request))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = generate_summary(_risk(), settings)

    assert result is None


def test_returns_none_when_response_has_no_text_block(monkeypatch: Any) -> None:
    fake_response = SimpleNamespace(content=[])
    fake_messages = _FakeMessages(response=fake_response)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: _FakeClient(fake_messages))

    settings = Settings(environment="test", anthropic_api_key="test-key")
    result = generate_summary(_risk(), settings)

    assert result is None
