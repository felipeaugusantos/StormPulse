"""Tests for the ZARC ingestion pipeline (item ZARC, ADR-0069).

Network calls are faked with ``httpx.MockTransport`` (same pattern as
``test_weather_inmet.py``/``test_satellite_pipeline.py``) — no live
download of MAPA's real, multi-megabyte CSV involved.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.zarc.models import ZarcRiskWindow
from workers.db import session_scope
from workers.zarc_pipeline import _parse_row, run_zarc_ingestion_cycle

pytestmark = pytest.mark.integration

_DECENDIO_HEADERS = ";".join(f"dec{i}" for i in range(1, 37))
_ZERO_DECENDIOS = ";".join("0" for _ in range(36))
_SOME_DECENDIOS = ";".join(("30" if i in (1, 2) else "0") for i in range(36))

_CSV_HEADER = (
    f"geocodigo;UF;municipio;Nome_cultura;Cod_Ciclo;Cod_Solo;SafraIni;SafraFin;"
    f"Portaria;{_DECENDIO_HEADERS}"
)


def _csv_body(*data_rows: str) -> str:
    return "\n".join([_CSV_HEADER, *data_rows])


def _handler_factory(body: str) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    return _handler


def _make_client(body: str) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler_factory(body)))


def test_parse_row_skips_a_row_with_every_decendio_zero() -> None:
    row = {
        "geocodigo": "3550308",
        "UF": "SP",
        "municipio": "São Paulo",
        "Nome_cultura": "Milho 1ª Safra",
        "Cod_Ciclo": "20",
        "Cod_Solo": "2",
        "SafraIni": "2026",
        "SafraFin": "2027",
        "Portaria": "Portaria 1/2026",
        **{f"dec{i}": "0" for i in range(1, 37)},
    }
    assert _parse_row(row) is None


def test_parse_row_returns_a_dict_for_a_valid_row() -> None:
    row = {
        "geocodigo": "3550308",
        "UF": "SP",
        "municipio": "São Paulo",
        "Nome_cultura": "Milho 1ª Safra",
        "Cod_Ciclo": "20",
        "Cod_Solo": "2",
        "SafraIni": "2026",
        "SafraFin": "2027",
        "Portaria": "Portaria 1/2026",
        **{f"dec{i}": ("30" if i == 1 else "0") for i in range(1, 37)},
    }
    parsed = _parse_row(row)
    assert parsed is not None
    assert parsed["geocodigo"] == "3550308"
    assert parsed["cod_ciclo"] == 20
    assert parsed["cod_solo"] == 2
    decendios = parsed["decendios"]
    assert isinstance(decendios, list)
    assert decendios[0] == 30
    assert decendios[1] == 0


def test_parse_row_returns_none_for_missing_required_field() -> None:
    row = {
        "geocodigo": "",
        "UF": "SP",
        "municipio": "São Paulo",
        "Nome_cultura": "Milho 1ª Safra",
        "Cod_Ciclo": "20",
        "Cod_Solo": "2",
        "SafraIni": "2026",
        "SafraFin": "2027",
        "Portaria": "",
        **{f"dec{i}": ("30" if i == 1 else "0") for i in range(1, 37)},
    }
    assert _parse_row(row) is None


def _cleanup(session: Session) -> None:
    session.rollback()


def test_disabled_returns_immediately_without_touching_the_table() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", zarc_enabled=False)
        summary = run_zarc_ingestion_cycle(session, settings=settings)
        assert summary.enabled is False
        assert summary.rows_ingested == 0
        _cleanup(session)


def test_ingestion_replaces_the_table_with_the_downloaded_rows() -> None:
    body = _csv_body(
        f"3550308;SP;São Paulo;Milho 1ª Safra;20;2;2026;2027;Portaria 1/2026;{_SOME_DECENDIOS}",
        f"3550308;SP;São Paulo;Soja;21;2;2026;2027;Portaria 2/2026;{_SOME_DECENDIOS}",
        f"3550308;SP;São Paulo;Café;13;1;2026;2027;;{_ZERO_DECENDIOS}",
    )
    with session_scope() as session:
        settings = Settings(environment="test", zarc_enabled=True)
        summary = run_zarc_ingestion_cycle(session, settings=settings, client=_make_client(body))
        assert summary.enabled is True
        # The all-zero "Café" row has no real window and must be skipped.
        assert summary.rows_ingested == 2

        rows = session.scalars(
            select(ZarcRiskWindow).where(ZarcRiskWindow.geocodigo == "3550308")
        ).all()
        assert {row.cultura for row in rows} == {"Milho 1ª Safra", "Soja"}
        _cleanup(session)


def test_ingestion_deletes_stale_rows_from_a_previous_cycle() -> None:
    first_body = _csv_body(
        f"3550308;SP;São Paulo;Milho 1ª Safra;20;2;2026;2027;Portaria 1/2026;{_SOME_DECENDIOS}"
    )
    second_body = _csv_body(
        f"3550308;SP;São Paulo;Soja;21;2;2026;2027;Portaria 2/2026;{_SOME_DECENDIOS}"
    )
    with session_scope() as session:
        settings = Settings(environment="test", zarc_enabled=True)
        run_zarc_ingestion_cycle(session, settings=settings, client=_make_client(first_body))
        run_zarc_ingestion_cycle(session, settings=settings, client=_make_client(second_body))

        rows = session.scalars(
            select(ZarcRiskWindow).where(ZarcRiskWindow.geocodigo == "3550308")
        ).all()
        assert {row.cultura for row in rows} == {"Soja"}
        _cleanup(session)
