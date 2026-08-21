"""Location CRUD endpoints (tenant + user scoped)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_request_settings
from app.core.config import Settings
from app.locations import service
from app.locations.models import Location
from app.locations.schemas import LocationCreate, LocationOut, LocationUpdate, SprayWindowOut
from app.storms import service as storm_service
from app.storms.schemas import StormRiskOut
from app.users.models import User
from app.weather.factory import get_numeric_rain_forecast_provider, get_weather_provider
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    RainfallHistory,
    WeatherProviderUnavailableError,
)

router = APIRouter(tags=["locations"])


async def _get_owned_or_404(session: AsyncSession, user: User, location_id: uuid.UUID) -> Location:
    location = await service.get_location(session, user, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")
    return location


async def _validate_parent(
    session: AsyncSession, user: User, parent_location_id: uuid.UUID | None
) -> None:
    """A talhão's parent must belong to the caller and not itself be a
    talhão — only one level of nesting (farm → plots), not a tree."""
    if parent_location_id is None:
        return
    parent = await service.get_location(session, user, parent_location_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fazenda (local pai) não encontrada"
        )
    if parent.parent_location_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Um talhão não pode ser filho de outro talhão",
        )


@router.post(
    "",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar local monitorado",
)
async def create_location(
    data: LocationCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    await _validate_parent(session, user, data.parent_location_id)
    return await service.create_location(session, user, data)


@router.get("", response_model=list[LocationOut], summary="Listar locais do usuário")
async def list_locations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Location]:
    return await service.list_locations(session, user)


@router.get("/{location_id}", response_model=LocationOut, summary="Detalhar local")
async def get_location(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    return await _get_owned_or_404(session, user, location_id)


@router.put("/{location_id}", response_model=LocationOut, summary="Atualizar local")
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    location = await _get_owned_or_404(session, user, location_id)
    return await service.update_location(session, location, data)


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover local",
)
async def delete_location(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    location = await _get_owned_or_404(session, user, location_id)
    await service.delete_location(session, location)


@router.get(
    "/{location_id}/risk",
    response_model=StormRiskOut,
    summary="Última avaliação de risco do local",
)
async def get_location_risk(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    location = await _get_owned_or_404(session, user, location_id)
    risk = await storm_service.latest_risk_for_location(session, location.id)
    if risk is None:
        # Honest 404: no risk has been computed yet (needs the storm engine).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma avaliação de risco disponível para este local ainda",
        )
    return risk


@router.get(
    "/{location_id}/forecast",
    response_model=Forecast,
    summary="Previsão do tempo para o local (fonte real, quando configurada)",
)
async def get_location_forecast(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> Forecast:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        return await provider.get_forecast(location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        # Honest 404: no fabricated forecast when the real source can't
        # produce one (no nearby station, IBGE geocode unresolved, or the
        # upstream API itself is down/unreachable — INMET's public API has
        # real-world downtime, confirmed during development).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Previsão indisponível para este local no momento",
        ) from exc


@router.get(
    "/{location_id}/current",
    response_model=CurrentConditions,
    summary="Condições atuais do local (fonte real, quando configurada)",
)
async def get_location_current(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> CurrentConditions:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        return await provider.get_current_data(location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condições atuais indisponíveis para este local no momento",
        ) from exc


@router.get(
    "/{location_id}/agro/spray-window",
    response_model=SprayWindowOut,
    summary="Janela de pulverização — vento + chuva prevista quando disponível (FASE 19/20)",
)
async def get_location_spray_window(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> SprayWindowOut:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        current = await provider.get_current_data(location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condições atuais indisponíveis para este local no momento",
        ) from exc

    # Rain is a bonus signal — only INMET/CPTEC never give a numeric
    # forecast at all (ADR-0011/0014), so this asks Open-Meteo directly
    # (ADR-0020) instead of the general provider chain, which would
    # otherwise stop at CPTEC (it "succeeds", just with no rain number) and
    # never actually reach Open-Meteo. A failure here still degrades
    # gracefully instead of 404ing the whole endpoint — wind alone is still
    # useful.
    rain_probability: int | None = None
    rain_mm: float | None = None
    try:
        rain_provider = get_numeric_rain_forecast_provider(settings)
        forecast = await rain_provider.get_forecast(location.latitude, location.longitude)
        today = datetime.now(UTC).date()
        today_point = next((p for p in forecast.points if p.time.date() == today), None)
        if today_point is not None:
            rain_probability = today_point.precipitation_probability
            rain_mm = today_point.precipitation_mm
    except (WeatherProviderUnavailableError, httpx.HTTPError):
        pass

    wind = current.wind_gusts_kmh if current.wind_gusts_kmh is not None else current.wind_kmh
    wind_safe = None if wind is None else wind < settings.agro_spray_max_wind_kmh
    rain_unsafe = (
        rain_probability is not None
        and rain_probability >= settings.agro_spray_max_rain_probability_percent
    )
    # Thermal inversion (ADR-0018): calm *steady* wind (not gusts — a gust
    # doesn't mean the air is mixing) plus high humidity is the classic
    # dawn signature that makes spray drift instead of settling. Only
    # evaluated when the source actually reports humidity.
    inversion_risk = (
        current.wind_kmh is not None
        and current.relative_humidity_percent is not None
        and current.wind_kmh <= settings.agro_spray_inversion_max_wind_kmh
        and current.relative_humidity_percent >= settings.agro_spray_inversion_min_humidity_percent
    )
    safe = None if wind_safe is None else (wind_safe and not rain_unsafe and not inversion_risk)

    return SprayWindowOut(
        wind_kmh=current.wind_kmh,
        wind_gusts_kmh=current.wind_gusts_kmh,
        max_wind_kmh=settings.agro_spray_max_wind_kmh,
        rain_probability_percent=rain_probability,
        rain_expected_mm=rain_mm,
        max_rain_probability_percent=settings.agro_spray_max_rain_probability_percent,
        humidity_percent=current.relative_humidity_percent,
        inversion_risk=inversion_risk,
        safe=safe,
    )


@router.get(
    "/{location_id}/agro/rain-forecast",
    response_model=Forecast,
    summary="Previsão de chuva numérica — Open-Meteo direto (FASE 24, ADR-0020)",
)
async def get_location_rain_forecast(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> Forecast:
    """Same shape as ``/forecast``, but always asks Open-Meteo directly —
    the only source that ever gives numeric ``precipitation_mm`` (see
    ``get_numeric_rain_forecast_provider``). Used by anything that needs to
    know *how much* rain is coming, not just the temperature — trafficability
    among them (see ``web/src/agro.ts``)."""
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_numeric_rain_forecast_provider(settings)
    try:
        return await provider.get_forecast(location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Previsão de chuva indisponível para este local no momento",
        ) from exc


@router.get(
    "/{location_id}/agro/rainfall",
    response_model=RainfallHistory,
    summary="Chuva acumulada por dia, janela recente (FASE 19)",
)
async def get_location_rainfall(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
    days: int = Query(default=15, ge=1, le=60),
) -> RainfallHistory:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        return await provider.get_recent_rainfall(location.latitude, location.longitude, days=days)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Histórico de chuva indisponível para este local no momento",
        ) from exc
