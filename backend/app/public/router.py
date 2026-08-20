"""Public (unauthenticated) read-only endpoints — "visitor mode" (FASE 15).

No personalized data (locations, risk) is ever exposed here — only storm
cells (already tenant-agnostic global data, see ``storms/service.py``) and
official warnings, fetched live from the active weather provider per point
(no persistence — see ADR-0008 for why).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import Settings, get_settings
from app.lightning import service as lightning_service
from app.lightning.schemas import LightningStrikeOut
from app.satellite import service as satellite_service
from app.satellite.schemas import ConvectiveWatchOut, SatelliteImageMetaOut
from app.storms import service as storm_service
from app.storms.schemas import NearbyStormCellOut, StormCellOut
from app.weather.factory import get_weather_provider
from app.weather.provider import Warning, WeatherProviderUnavailableError

router = APIRouter(tags=["public"])


@router.get("/storms", response_model=list[StormCellOut], summary="Células recentes (público)")
async def public_storms(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> object:
    return await storm_service.list_recent_cells(session, limit=limit)


@router.get(
    "/storms/nearby",
    response_model=list[NearbyStormCellOut],
    summary="Células próximas de um ponto (público, ST_DWithin)",
)
async def public_storms_nearby(
    session: AsyncSession = Depends(get_db),
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50.0, gt=0, le=500),
) -> list[NearbyStormCellOut]:
    pairs = await storm_service.cells_within_radius(
        session, latitude=lat, longitude=lon, radius_km=radius_km
    )
    return [
        NearbyStormCellOut(
            **StormCellOut.model_validate(cell).model_dump(),
            distance_km=round(dist, 2),
        )
        for cell, dist in pairs
    ]


@router.get(
    "/satellite/watches",
    response_model=list[ConvectiveWatchOut],
    summary="Observações via satélite ativas (público)",
)
async def public_satellite_watches(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> object:
    return await satellite_service.list_active_watches(session, limit=limit)


@router.get(
    "/satellite/image",
    response_model=SatelliteImageMetaOut,
    summary="Metadados do quadro de satélite atual (público)",
)
async def public_satellite_image_meta(
    session: AsyncSession = Depends(get_db),
) -> SatelliteImageMetaOut:
    image = await satellite_service.get_latest_image(session)
    if image is None:
        # Honest 404: SATELLITE_ENABLED=false, or no cycle has run yet —
        # never a placeholder/blank image pretending to be real.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma imagem de satélite disponível no momento",
        )
    return SatelliteImageMetaOut(
        captured_at=image.captured_at,
        bbox=(image.bbox_lon_min, image.bbox_lat_min, image.bbox_lon_max, image.bbox_lat_max),
        band=image.band,
        width=image.width,
        height=image.height,
    )


@router.get(
    "/satellite/image.png",
    summary="PNG do quadro de satélite atual (público, sem autenticação — usado direto pelo mapa)",
)
async def public_satellite_image_png(
    session: AsyncSession = Depends(get_db),
) -> Response:
    image = await satellite_service.get_latest_image(session)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma imagem de satélite disponível no momento",
        )
    return Response(
        content=image.png_data,
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@router.get(
    "/lightning",
    response_model=list[LightningStrikeOut],
    summary="Raios recentes (público)",
)
async def public_lightning(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> object:
    return await lightning_service.list_recent_strikes(session, limit=limit)


@router.get(
    "/warnings",
    response_model=list[Warning],
    summary="Avisos oficiais ativos perto de um ponto (público, ao vivo)",
)
async def public_warnings(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    settings: Settings = Depends(get_settings),
) -> list[Warning]:
    provider = get_weather_provider(settings)
    try:
        return await provider.get_warnings(lat, lon)
    except (WeatherProviderUnavailableError, httpx.HTTPError):
        # Honest empty list, not a 500: the same "no warnings available"
        # outcome InmetWeatherProvider.get_warnings already returns for a
        # partial failure — this just extends it to a full provider outage.
        return []
