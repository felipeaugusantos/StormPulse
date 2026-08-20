"""Tests for the mock weather provider and the provider factory."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.enums import WeatherSourceKind
from app.weather.cptec import CptecWeatherProvider
from app.weather.factory import get_weather_provider
from app.weather.fallback import FallbackWeatherProvider
from app.weather.inmet import InmetWeatherProvider
from app.weather.mock import MockWeatherProvider


@pytest.fixture
def provider() -> MockWeatherProvider:
    return MockWeatherProvider()


async def test_current_data_is_flagged_mock(provider: MockWeatherProvider) -> None:
    data = await provider.get_current_data(-23.5, -46.6)
    assert data.provenance.is_mock is True
    assert data.provenance.source_kind is WeatherSourceKind.MOCK


async def test_radar_frames_are_deterministic(provider: MockWeatherProvider) -> None:
    a = await provider.get_radar_frames(limit=3)
    b = await provider.get_radar_frames(limit=3)
    assert len(a) == 3
    assert all(f.provenance.is_mock for f in a)
    # Deterministic cell geometry (timestamps aside).
    assert [c.latitude for f in a for c in f.cells] == [c.latitude for f in b for c in f.cells]


async def test_forecast_has_points(provider: MockWeatherProvider) -> None:
    forecast = await provider.get_forecast(-23.5, -46.6)
    assert forecast.provenance.is_mock is True
    assert len(forecast.points) == 12


def test_factory_returns_mock_by_default() -> None:
    provider = get_weather_provider(Settings(environment="test"))
    assert isinstance(provider, MockWeatherProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown weather provider"):
        get_weather_provider(Settings(environment="test", weather_provider="nao_existe"))


def test_factory_wraps_inmet_with_cptec_fallback_by_default() -> None:
    provider = get_weather_provider(
        Settings(environment="test", weather_provider="inmet", cptec_fallback_enabled=True)
    )
    assert isinstance(provider, FallbackWeatherProvider)


def test_factory_returns_bare_inmet_when_fallback_disabled() -> None:
    provider = get_weather_provider(
        Settings(environment="test", weather_provider="inmet", cptec_fallback_enabled=False)
    )
    assert isinstance(provider, InmetWeatherProvider)


def test_factory_returns_cptec_standalone() -> None:
    provider = get_weather_provider(Settings(environment="test", weather_provider="cptec"))
    assert isinstance(provider, CptecWeatherProvider)
