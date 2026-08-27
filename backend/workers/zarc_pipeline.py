"""ZARC planting-window ingestion (item ZARC, ADR-0069).

Downloads MAPA's public "Tábua de Risco" CSV for the current safra
(``dados.agricultura.gov.br`` — a static file, no queryable API/datastore
exists for it, confirmed against the dataset's own CKAN metadata) and
replaces the whole ``zarc_risk_windows`` table with it. A full
delete-then-insert, not an upsert: this is reference data with no foreign
keys pointing at individual rows, and the safra's own official portarias
occasionally get amended/superseded — a stale row from a previous
download must never linger next to its replacement.

Runs weekly (see ``workers/celery_app.py``), matching the source's own
publication cadence — no benefit to checking a static government CSV more
often than that.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.zarc.models import ZarcRiskWindow

logger = logging.getLogger(__name__)

_DECENDIO_COLUMNS = [f"dec{i}" for i in range(1, 37)]
_BATCH_SIZE = 2000


@dataclass
class ZarcCycleSummary:
    enabled: bool
    rows_ingested: int = 0


def _parse_row(row: dict[str, str]) -> dict[str, object] | None:
    """Returns the ORM-ready field dict for one CSV row, or ``None`` when
    the row has no actual planting window (every decêndio is 0 — the
    município/cultura/ciclo/solo combination simply isn't zoned there,
    same distinction the MAPA data itself encodes)."""
    try:
        decendios = [int(row[col] or 0) for col in _DECENDIO_COLUMNS]
    except (KeyError, ValueError):
        return None
    if not any(decendios):
        return None

    geocodigo = row.get("geocodigo")
    uf = row.get("UF")
    municipio = row.get("municipio")
    cultura = row.get("Nome_cultura")
    if not geocodigo or not uf or not municipio or not cultura:
        return None

    try:
        cod_ciclo = int(row["Cod_Ciclo"])
        cod_solo = int(row["Cod_Solo"])
        safra_ini = int(row["SafraIni"])
        safra_fin = int(row["SafraFin"])
    except (KeyError, ValueError):
        return None

    return {
        "geocodigo": str(geocodigo),
        "uf": str(uf),
        "municipio": str(municipio),
        "cultura": str(cultura),
        "cod_ciclo": cod_ciclo,
        "cod_solo": cod_solo,
        "safra_ini": safra_ini,
        "safra_fin": safra_fin,
        "portaria": row.get("Portaria") or None,
        "decendios": decendios,
    }


def run_zarc_ingestion_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> ZarcCycleSummary:
    settings = settings or get_settings()
    if not settings.zarc_enabled:
        return ZarcCycleSummary(enabled=False)

    # Deleted *before* the new rows are inserted, but never committed here
    # — this function never calls session.commit()/rollback() itself, so
    # the caller's own transaction (workers.db.session_scope) is what
    # actually makes the replace atomic: if the download below raises
    # partway through, session_scope's rollback undoes this delete too,
    # and the previous cycle's data is exactly what's left in place.
    session.execute(delete(ZarcRiskWindow))

    rows_ingested = 0
    batch: list[dict[str, object]] = []

    own_client = client is None
    client = client or httpx.Client(timeout=settings.zarc_http_timeout_seconds)
    try:
        with client.stream("GET", settings.zarc_csv_url) as response:
            response.raise_for_status()
            response.encoding = "utf-8"
            reader = csv.DictReader(response.iter_lines(), delimiter=";")
            for raw_row in reader:
                parsed = _parse_row(raw_row)
                if parsed is None:
                    continue
                batch.append(parsed)
                if len(batch) >= _BATCH_SIZE:
                    session.execute(insert(ZarcRiskWindow), batch)
                    rows_ingested += len(batch)
                    batch = []
            if batch:
                session.execute(insert(ZarcRiskWindow), batch)
                rows_ingested += len(batch)
    finally:
        if own_client:
            client.close()

    logger.info("ZARC ingestion cycle complete", extra={"rows_ingested": rows_ingested})
    return ZarcCycleSummary(enabled=True, rows_ingested=rows_ingested)
