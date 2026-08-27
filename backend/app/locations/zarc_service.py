"""ZARC planting-window lookup for a single talhão — item ZARC, ADR-0069.

Purely a read against the already-ingested ``zarc_risk_windows`` reference
table (see ``workers/zarc_pipeline.py``) plus the município geocode
resolver (``app.zarc.geocode``) — never calls MAPA/IBGE/INMET live on the
request path beyond what the geocode resolver itself needs.
"""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.locations.models import Location
from app.locations.schemas import ZarcMatchOut, ZarcWindowOut
from app.weather.inmet import _normalize_name
from app.zarc.geocode import MunicipioNotResolvedError, resolve_municipio_geocode
from app.zarc.models import ZarcRiskWindow

# Cod_Solo values from MAPA's own data dictionary (item ZARC, ADR-0069) —
# only the three main texture classes are offered by the talhão's
# soil_type picker (see LocationBase.soil_type), the specialized AD1-AD6
# water-holding-capacity classes some crops also publish aren't exposed.
_SOIL_TYPE_TO_COD_SOLO = {"arenoso": 1, "textura_media": 2, "argiloso": 3}

# Cod_Ciclo → human label, from MAPA's data dictionary.
_CICLO_LABELS = {
    13: "Perene",
    19: "Semiperene",
    20: "Grupo I",
    21: "Grupo II",
    22: "Grupo III",
    24: "Grupo IV",
    25: "Grupo V",
    26: "Grupo VI",
}


class ZarcLookupUnavailableError(Exception):
    """Raised when the talhão is missing data needed for a ZARC lookup
    (no crop, no soil_type) or its município couldn't be resolved."""


async def get_zarc_window(
    session: AsyncSession,
    location: Location,
    settings: Settings,
    *,
    geocode_client: httpx.AsyncClient | None = None,
) -> ZarcWindowOut:
    if not location.crop or not location.soil_type:
        raise ZarcLookupUnavailableError(
            "Talhão precisa ter cultura e tipo de solo definidos para consultar o ZARC"
        )
    cod_solo = _SOIL_TYPE_TO_COD_SOLO[location.soil_type]

    try:
        geocodigo = await resolve_municipio_geocode(
            location.latitude,
            location.longitude,
            inmet_base_url=settings.inmet_base_url,
            ibge_localidades_url=settings.ibge_localidades_url,
            http_timeout_seconds=settings.zarc_http_timeout_seconds,
            client=geocode_client,
        )
    except MunicipioNotResolvedError as exc:
        raise ZarcLookupUnavailableError(str(exc)) from exc

    result = await session.execute(
        select(ZarcRiskWindow).where(
            ZarcRiskWindow.geocodigo == geocodigo,
            ZarcRiskWindow.cod_solo == cod_solo,
        )
    )
    rows = list(result.scalars().all())
    target_crop = _normalize_name(location.crop)
    matched = [row for row in rows if target_crop in _normalize_name(row.cultura)]

    if not matched:
        raise ZarcLookupUnavailableError(
            f"Nenhuma janela ZARC encontrada para '{location.crop}' no solo "
            f"informado neste município"
        )

    municipio = matched[0].municipio
    uf = matched[0].uf
    matches = [
        ZarcMatchOut(
            cultura=row.cultura,
            cod_ciclo=row.cod_ciclo,
            ciclo_label=_CICLO_LABELS.get(row.cod_ciclo, f"Ciclo {row.cod_ciclo}"),
            safra_ini=row.safra_ini,
            safra_fin=row.safra_fin,
            portaria=row.portaria,
            decendios=row.decendios,
        )
        for row in matched
    ]
    return ZarcWindowOut(
        location_id=location.id,
        geocodigo=geocodigo,
        municipio=municipio,
        uf=uf,
        matches=matches,
    )
