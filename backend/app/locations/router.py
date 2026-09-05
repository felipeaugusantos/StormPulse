"""Location CRUD endpoints (tenant + user scoped)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_redis, get_request_settings
from app.core.config import Settings
from app.core.enums import VegetationIndex
from app.core.metrics import record_weather_data_age
from app.deforestation.models import DeforestationCheck
from app.deforestation.provider import DeforestationAlert
from app.forecast_comparison.service import get_model_comparison
from app.locations import service
from app.locations.models import Location
from app.locations.pdf import render_weekly_report_pdf
from app.locations.schemas import (
    DeforestationCheckOut,
    ForecastComparisonOut,
    LocationCreate,
    LocationOut,
    LocationUpdate,
    ModelMetricsOut,
    PrecipitationErrorOut,
    SprayWindowOut,
    WeeklyReportOut,
    ZarcWindowOut,
)
from app.locations.zarc_service import ZarcLookupUnavailableError, get_zarc_window
from app.ndvi import service as vegetation_service
from app.ndvi.models import NdviImage, NdviReading
from app.ndvi.schemas import (
    NdviOut,
    VegetationComparisonOut,
    VegetationSeriesOut,
)
from app.storms import service as storm_service
from app.storms.schemas import StormRiskOut
from app.users.models import User
from app.weather.cache import get_cached, set_cached
from app.weather.factory import get_numeric_rain_forecast_provider, get_weather_provider
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    RainfallHistory,
    WeatherProvider,
    WeatherProviderUnavailableError,
)
from engine.geo import haversine_km

router = APIRouter(tags=["locations"])


async def _get_owned_or_404(session: AsyncSession, user: User, location_id: uuid.UUID) -> Location:
    location = await service.get_location(session, user, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")
    return location


async def _validate_parent(
    session: AsyncSession, user: User, parent_location_id: uuid.UUID | None
) -> Location | None:
    """A talhão's parent must belong to the caller and not itself be a
    talhão — only one level of nesting (farm → plots), not a tree."""
    if parent_location_id is None:
        return None
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
    return parent


async def _cached_current(
    redis: Redis | None, provider: WeatherProvider, latitude: float, longitude: float
) -> CurrentConditions:
    """Shared by ``/current`` and ``/agro/spray-window`` (which needs the
    same reading internally) — see ``app.weather.cache`` for why this
    exists: the dashboard's ~30s auto-refresh made this the single most
    frequent call into the (rate/quota-limited) Open-Meteo forecast
    endpoint, and a real production incident traced back to exactly that.
    """
    cached = await get_cached(redis, "current", latitude, longitude, CurrentConditions)
    if cached is not None:
        return cached
    current = await provider.get_current_data(latitude, longitude)
    await set_cached(redis, "current", latitude, longitude, current)
    return current


async def _cached_forecast(
    redis: Redis | None, provider: WeatherProvider, kind: str, latitude: float, longitude: float
) -> Forecast:
    """``kind`` keeps the general chained forecast (``"forecast"``, may be
    answered by INMET/CPTEC/Open-Meteo depending on availability) and the
    numeric rain forecast (``"rain-forecast"``, always Open-Meteo direct —
    see ``get_numeric_rain_forecast_provider``) in separate cache entries,
    since they're never interchangeable content even for the same point.
    """
    cached = await get_cached(redis, kind, latitude, longitude, Forecast)
    if cached is not None:
        return cached
    forecast = await provider.get_forecast(latitude, longitude)
    await set_cached(redis, kind, latitude, longitude, forecast)
    return forecast


def _validate_boundary_within_parent_radius(parent: Location, boundary_geojson: str) -> None:
    """A talhão's drawn contour must fall inside its farm's own monitored
    radius — otherwise it's easy to click/drag a boundary onto the wrong
    spot on the map and end up with a plot the farm's alerts/weather never
    actually cover."""
    ring = json.loads(boundary_geojson)["coordinates"][0]
    for lon, lat in ring:
        distance_km = haversine_km(parent.latitude, parent.longitude, lat, lon)
        if distance_km > parent.radius_km:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "O contorno do talhão precisa ficar dentro do raio monitorado da "
                    f"fazenda ({parent.radius_km:.0f} km) — um ponto do contorno está a "
                    f"{distance_km:.1f} km do centro da fazenda"
                ),
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
    parent = await _validate_parent(session, user, data.parent_location_id)
    if parent is not None and data.boundary_geojson is not None:
        _validate_boundary_within_parent_radius(parent, data.boundary_geojson)
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
    if data.boundary_geojson is not None and location.parent_location_id is not None:
        parent = await service.get_location(session, user, location.parent_location_id)
        if parent is not None:
            _validate_boundary_within_parent_radius(parent, data.boundary_geojson)
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
    redis: Redis | None = Depends(get_redis),
) -> Forecast:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        return await _cached_forecast(
            redis, provider, "forecast", location.latitude, location.longitude
        )
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
    redis: Redis | None = Depends(get_redis),
) -> CurrentConditions:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        current = await _cached_current(redis, provider, location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condições atuais indisponíveis para este local no momento",
        ) from exc
    record_weather_data_age(current.observed_at, current.provenance.source_name)
    return current


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
    redis: Redis | None = Depends(get_redis),
) -> SprayWindowOut:
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_weather_provider(settings)
    try:
        current = await _cached_current(redis, provider, location.latitude, location.longitude)
    except (WeatherProviderUnavailableError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condições atuais indisponíveis para este local no momento",
        ) from exc
    record_weather_data_age(current.observed_at, current.provenance.source_name)

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
        forecast = await _cached_forecast(
            redis, rain_provider, "rain-forecast", location.latitude, location.longitude
        )
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
    redis: Redis | None = Depends(get_redis),
) -> Forecast:
    """Same shape as ``/forecast``, but always asks Open-Meteo directly —
    the only source that ever gives numeric ``precipitation_mm`` (see
    ``get_numeric_rain_forecast_provider``). Used by anything that needs to
    know *how much* rain is coming, not just the temperature — trafficability
    among them (see ``web/src/agro.ts``)."""
    location = await _get_owned_or_404(session, user, location_id)
    provider = get_numeric_rain_forecast_provider(settings)
    try:
        return await _cached_forecast(
            redis, provider, "rain-forecast", location.latitude, location.longitude
        )
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


@router.get(
    "/{location_id}/agro/ndvi",
    response_model=NdviOut,
    summary="Última leitura de NDVI do talhão (FASE 29, ADR-0053)",
)
async def get_location_ndvi(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NdviReading:
    """Reads the most recent `NdviReading` already computed by the
    background pipeline — never calls the NDVI provider live (unlike the
    weather endpoints above), since a Sentinel Hub request is heavier and
    quota-limited, not something to spend on every dashboard refresh.

    Only ever has data for a talhão (`parent_location_id` set) with a drawn
    `boundary_geojson` — a farm-level point, or a talhão that hasn't had a
    pipeline cycle run yet, both 404 the same honest way "no data" would.
    """
    location = await _get_owned_or_404(session, user, location_id)
    stmt = (
        select(NdviReading)
        .where(
            NdviReading.location_id == location.id,
            NdviReading.index_name == VegetationIndex.NDVI.value,
        )
        .order_by(NdviReading.observed_at.desc())
        .limit(1)
    )
    reading = (await session.execute(stmt)).scalar_one_or_none()
    if reading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma leitura de NDVI disponível para este talhão ainda",
        )
    return reading


@router.get(
    "/{location_id}/agro/ndvi-image",
    summary='Imagem de NDVI colorida do talhão (item "imagem do talhão")',
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_location_ndvi_image(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Same "read what the background pipeline already computed, never
    call the provider live" rule as `/agro/ndvi` above. This compatibility
    endpoint returns the latest NDVI map; dated maps remain available from
    the multi-index historical endpoint."""
    location = await _get_owned_or_404(session, user, location_id)
    image = (
        await session.execute(
            select(NdviImage)
            .where(
                NdviImage.location_id == location.id,
                NdviImage.index_name == VegetationIndex.NDVI.value,
            )
            .order_by(NdviImage.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma imagem de NDVI disponível para este talhão ainda",
        )
    return Response(content=image.png_data, media_type="image/png")


@router.get(
    "/{location_id}/agro/vegetation",
    response_model=VegetationSeriesOut,
    summary="Série histórica e inteligência de um índice espectral do talhão",
)
async def get_location_vegetation_series(
    location_id: uuid.UUID,
    index_name: VegetationIndex = Query(VegetationIndex.NDVI, alias="index"),
    days: int = Query(365, ge=1, le=730),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VegetationSeriesOut:
    location = await _get_owned_or_404(session, user, location_id)
    if location.parent_location_id is None or location.boundary_geojson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Índices espectrais exigem um talhão com contorno completo",
        )
    return await vegetation_service.get_series(
        session, location_id=location.id, index_name=index_name, days=days
    )


@router.get(
    "/{location_id}/agro/vegetation/compare",
    response_model=VegetationComparisonOut,
    summary="Compara duas aquisições confiáveis do mesmo índice",
)
async def compare_location_vegetation(
    location_id: uuid.UUID,
    index_name: VegetationIndex = Query(VegetationIndex.NDVI, alias="index"),
    older_date: date | None = Query(None),
    newer_date: date | None = Query(None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VegetationComparisonOut:
    location = await _get_owned_or_404(session, user, location_id)
    series = await vegetation_service.get_series(
        session, location_id=location.id, index_name=index_name, days=730
    )
    comparison = vegetation_service.compare_readings(
        location_id=location.id,
        index_name=index_name,
        series=series.series,
        older_date=older_date,
        newer_date=newer_date,
    )
    if comparison is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="São necessárias duas imagens confiáveis, em datas diferentes, para comparar",
        )
    return comparison


@router.get(
    "/{location_id}/agro/vegetation/image.png",
    summary="Mapa histórico de índice espectral com metadados de qualidade",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_location_vegetation_image(
    location_id: uuid.UUID,
    index_name: VegetationIndex = Query(VegetationIndex.NDVI, alias="index"),
    observed_at: datetime | None = Query(None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    location = await _get_owned_or_404(session, user, location_id)
    stmt = select(NdviImage).where(
        NdviImage.location_id == location.id,
        NdviImage.index_name == index_name.value,
    )
    if observed_at is not None:
        stmt = stmt.where(NdviImage.observed_at == observed_at)
    image = (
        (await session.execute(stmt.order_by(NdviImage.observed_at.desc()).limit(1)))
        .scalars()
        .one_or_none()
    )
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma imagem válida encontrada para o índice e a data solicitados",
        )
    return Response(
        content=image.png_data,
        media_type="image/png",
        headers={
            "X-Vegetation-Index": image.index_name.upper(),
            "X-Observed-At": image.observed_at.isoformat(),
            "X-Source": image.source_name,
            "X-Image-Quality": image.quality,
            "X-Cloud-Coverage-Percent": str(image.cloud_cover_percent),
            "X-Reliable": str(image.reliable).lower(),
        },
    )


@router.get(
    "/{location_id}/agro/vegetation/export.csv",
    summary="Exporta a série histórica de um índice espectral",
    response_class=Response,
)
async def export_location_vegetation_series(
    location_id: uuid.UUID,
    index_name: VegetationIndex = Query(VegetationIndex.NDVI, alias="index"),
    days: int = Query(730, ge=1, le=730),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    location = await _get_owned_or_404(session, user, location_id)
    series = await vegetation_service.get_series(
        session, location_id=location.id, index_name=index_name, days=days
    )
    if not series.series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma observação disponível para exportar",
        )
    filename = f"{location.id}-{index_name.value}-series.csv"
    return Response(
        content=vegetation_service.series_csv(series),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{location_id}/agro/deforestation",
    response_model=DeforestationCheckOut,
    summary="Checagem de desmatamento (DETER/PRODES, INPE) do talhão (item DETER)",
)
async def get_location_deforestation(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeforestationCheckOut:
    """Reads whatever the background pipeline last successfully persisted
    per source (``workers/deforestation_pipeline.py``) — never calls INPE's
    WFS live, same "read what the pipeline already computed" rule as
    `/agro/ndvi` (that endpoint's own WFS proved unstable enough in
    development to make a live call on the request path a bad idea).
    Talhão-only (same scoping as NDVI/ZARC)."""
    location = await _get_owned_or_404(session, user, location_id)
    if location.parent_location_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checagem de desmatamento só está disponível para talhões",
        )
    rows = list(
        (
            await session.execute(
                select(DeforestationCheck).where(DeforestationCheck.location_id == location.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma checagem de desmatamento disponível para este talhão ainda",
        )
    alerts: list[DeforestationAlert] = []
    for row in rows:
        alerts.extend(DeforestationAlert.model_validate(a) for a in json.loads(row.alerts_json))
    return DeforestationCheckOut(
        checked_sources=[row.source for row in rows],
        last_checked_at=max(row.checked_at for row in rows),
        alerts=alerts,
    )


@router.get(
    "/{location_id}/agro/weekly-report",
    response_model=WeeklyReportOut,
    summary="Relatório semanal do talhão — chuva, alertas e NDVI (FASE 32)",
)
async def get_location_weekly_report(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> WeeklyReportOut:
    """Summarizes the last 7 full days for a talhão — something concrete to
    print or show an agronomist/bank, not just live numbers. Talhão-only
    (same scoping as NDVI): a farm-level point has no crop/alerts of its
    own to summarize this way.
    """
    location = await _get_owned_or_404(session, user, location_id)
    if location.parent_location_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório semanal só está disponível para talhões",
        )
    return await service.build_weekly_report(session, location, settings)


@router.get(
    "/{location_id}/agro/weekly-report/pdf",
    summary="Relatório semanal do talhão em PDF (item 2, ADR-0063)",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_location_weekly_report_pdf(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> Response:
    """Same data and scoping as the JSON weekly report above, rendered as a
    downloadable PDF — something to actually hand an agronomist or attach
    to a bank loan application, not just read on a dashboard."""
    location = await _get_owned_or_404(session, user, location_id)
    if location.parent_location_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório semanal só está disponível para talhões",
        )
    report = await service.build_weekly_report(session, location, settings)
    ndvi_image = (
        await session.execute(select(NdviImage).where(NdviImage.location_id == location.id))
    ).scalar_one_or_none()
    pdf_bytes = render_weekly_report_pdf(
        report, ndvi_image_png=ndvi_image.png_data if ndvi_image else None
    )
    filename = f"relatorio-semanal-{location.name}-{report.period_end}.pdf".replace(" ", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{location_id}/agro/zarc-window",
    response_model=ZarcWindowOut,
    summary="Janela de plantio oficial (ZARC/MAPA) do talhão (ADR-0069)",
)
async def get_location_zarc_window(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> ZarcWindowOut:
    """Informational-only planting-window lookup against MAPA's own
    published Tábua de Risco (item ZARC) — talhão-only (same scoping as
    NDVI/weekly-report): a farm-level point has no crop/soil of its own to
    look up. Never generates an alert on its own."""
    location = await _get_owned_or_404(session, user, location_id)
    if location.parent_location_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Janela ZARC só está disponível para talhões",
        )
    try:
        return await get_zarc_window(session, location, settings)
    except ZarcLookupUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{location_id}/forecast-comparison",
    response_model=ForecastComparisonOut,
    summary="Comparação de acurácia entre modelos meteorológicos (Fase 2, ADR-0082)",
)
async def get_location_forecast_comparison(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> ForecastComparisonOut:
    """Per-model accuracy for this location, accumulated by the daily
    snapshot/observation jobs (``app.forecast_comparison.service``) — not a
    live computation. Applies to any location (farm or talhão), unlike
    ZARC/NDVI above: the comparison is about the geographic point's forecast
    models, not a crop-specific signal. An empty ``models`` list is the
    honest answer for a brand-new location — nothing has been observed for
    it yet, never a fabricated placeholder."""
    location = await _get_owned_or_404(session, user, location_id)
    metrics = await get_model_comparison(session, location_id=location.id, settings=settings)
    return ForecastComparisonOut(
        location_id=location.id,
        min_sample_size=settings.forecast_comparison_min_sample_size,
        models=[
            ModelMetricsOut(
                model=m.model,
                sample_count=m.sample_count,
                has_enough_samples=m.has_enough_samples,
                temperature_mae_c=m.temperature_mae_c,
                precipitation=(
                    PrecipitationErrorOut(
                        bias_mm=m.precipitation.bias_mm,
                        mae_mm=m.precipitation.mae_mm,
                        sample_count=m.precipitation.sample_count,
                    )
                    if m.precipitation
                    else None
                ),
                wind_mae_kmh=m.wind_mae_kmh,
                rain_hit_rate=m.rain_hit_rate,
                brier_score=m.brier_score,
            )
            for m in metrics
        ],
    )
