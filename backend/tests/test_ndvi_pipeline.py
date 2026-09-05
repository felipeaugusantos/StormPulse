"""Tests for the NDVI-per-talhão pipeline (FASE 29, ADR-0053).

Same pattern as ``test_agro_pipeline.py``: tenant/user/location(s) built
directly in the sync session and rolled back at the end, never committed,
so repeated runs never pollute the shared dev database. The shared dev DB
may carry other real, active talhões (this pipeline correctly checks every
one of them) — every assertion here is scoped to this test's own
location(s), never to the aggregate summary counts, same reasoning as
``test_agro_pipeline.py``. A small fake ``NdviProvider`` stands in for
Copernicus so this exercises only the pipeline's own decision logic (which
talhões qualify, per-talhão failure isolation), never a real network call.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import blind_index
from app.core.enums import WeatherSourceKind
from app.locations.models import Location
from app.ndvi.models import NdviImage, NdviReading
from app.ndvi.provider import NdviObservation, NdviProvider, NdviProviderUnavailableError
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.provider import Provenance
from workers.db import session_scope
from workers.ndvi_pipeline import run_ndvi_pipeline_cycle

pytestmark = pytest.mark.integration

_BOUNDARY = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [[[-47.81, -21.18], [-47.80, -21.18], [-47.80, -21.17], [-47.81, -21.18]]],
    }
)


def _enabled_settings() -> Settings:
    # Never actually used to make a real call — every test here injects its
    # own fake provider, bypassing the factory that would otherwise read
    # these — but Settings itself still validates the combination at
    # construction time (see config.py's validator), so it needs *some*
    # non-empty value here regardless.
    return Settings(
        environment="test",
        ndvi_enabled=True,
        ndvi_sh_client_id="fake",
        ndvi_sh_client_secret="fake",
    )


class _FakeNdviProvider(NdviProvider):
    """Returns a fixed value, or raises when called with a specific
    boundary — lets a test exercise "one talhão fails, others don't"
    without depending on call order."""

    def __init__(self, *, ndvi_mean: float = 0.55, fail_for_boundary: str | None = None) -> None:
        self._ndvi_mean = ndvi_mean
        self._fail_for_boundary = fail_for_boundary

    @property
    def name(self) -> str:
        return "FAKE"

    async def get_ndvi(self, boundary_geojson: str, *, lookback_days: float) -> NdviObservation:
        if boundary_geojson == self._fail_for_boundary:
            raise NdviProviderUnavailableError("sem pixel válido (fake)")
        return NdviObservation(
            provenance=Provenance(
                source_name="FAKE", source_kind=WeatherSourceKind.SATELLITE, is_mock=True
            ),
            observed_at=datetime.now(UTC),
            ndvi_mean=self._ndvi_mean,
            valid_pixel_percent=90.0,
        )

    async def get_ndvi_image(self, boundary_geojson: str, *, lookback_days: float) -> bytes:
        return b"\x89PNG\r\n\x1a\nfake"


def _make_farm(session: Session) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"ndvi-{unique}@example.com"
    user = User(
        tenant_id=tenant.id,
        email=email,
        email_index=blind_index(email),
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(user)
    session.flush()
    farm = Location(
        tenant_id=tenant.id,
        user_id=user.id,
        name="Fazenda (teste)",
        kind="farm",
        latitude=-21.1775,
        longitude=-47.8103,
        radius_km=10,
        is_active=True,
    )
    session.add(farm)
    session.flush()
    return farm


def _make_talhao(
    session: Session,
    farm: Location,
    *,
    boundary_geojson: str | None = _BOUNDARY,
    is_active: bool = True,
) -> Location:
    talhao = Location(
        tenant_id=farm.tenant_id,
        user_id=farm.user_id,
        parent_location_id=farm.id,
        name="Talhão (teste)",
        kind="other",
        latitude=farm.latitude,
        longitude=farm.longitude,
        radius_km=1,
        boundary_geojson=boundary_geojson,
        is_active=is_active,
    )
    session.add(talhao)
    session.flush()
    return talhao


def _has_reading_for(session: Session, location_id: object) -> bool:
    return (
        session.scalars(select(NdviReading).where(NdviReading.location_id == location_id)).first()
        is not None
    )


def test_disabled_by_default_is_a_noop() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", ndvi_enabled=False)
        summary = run_ndvi_pipeline_cycle(session, settings=settings)
        assert summary.enabled is False
        assert summary.talhoes_checked == 0
        session.rollback()


def test_reading_created_for_eligible_talhao() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)
        provider = _FakeNdviProvider(ndvi_mean=0.62)

        summary = run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        assert summary.enabled is True
        reading = session.scalars(
            select(NdviReading).where(NdviReading.location_id == talhao.id)
        ).one()
        assert reading.ndvi_mean == 0.62
        assert reading.tenant_id == talhao.tenant_id
        assert reading.is_mock is True
        image = session.scalars(select(NdviImage).where(NdviImage.location_id == talhao.id)).one()
        assert image.png_data == b"\x89PNG\r\n\x1a\nfake"
        assert image.tenant_id == talhao.tenant_id
        session.rollback()


def test_ndvi_images_are_retained_for_historical_comparison() -> None:
    """Distinct acquisitions remain available for side-by-side comparison."""
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)

        run_ndvi_pipeline_cycle(
            session, settings=_enabled_settings(), provider=_FakeNdviProvider(ndvi_mean=0.5)
        )
        run_ndvi_pipeline_cycle(
            session, settings=_enabled_settings(), provider=_FakeNdviProvider(ndvi_mean=0.7)
        )

        images = session.scalars(select(NdviImage).where(NdviImage.location_id == talhao.id)).all()
        assert len(images) == 2
        session.rollback()


def test_ndvi_image_failure_does_not_undo_the_numeric_reading() -> None:
    """A picture is a bonus on top of the number, not a requirement for
    it — the image call failing must leave the numeric reading intact."""

    class _NoImageProvider(_FakeNdviProvider):
        async def get_ndvi_image(self, boundary_geojson: str, *, lookback_days: float) -> bytes:
            raise NdviProviderUnavailableError("sem imagem (fake)")

    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)
        provider = _NoImageProvider(ndvi_mean=0.62)

        run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        # Scoped to this test's own talhão, never the aggregate summary
        # counts — the shared dev DB may carry other real, active talhões
        # this same cycle also processes (see this file's own docstring).
        assert _has_reading_for(session, talhao.id)
        image = session.scalars(
            select(NdviImage).where(NdviImage.location_id == talhao.id)
        ).one_or_none()
        assert image is None
        session.rollback()


def test_farm_without_boundary_is_never_checked() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        provider = _FakeNdviProvider()

        run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        assert not _has_reading_for(session, farm.id)
        session.rollback()


def test_talhao_without_boundary_is_never_checked() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm, boundary_geojson=None)
        provider = _FakeNdviProvider()

        run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        assert not _has_reading_for(session, talhao.id)
        session.rollback()


def test_inactive_talhao_is_never_checked() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm, is_active=False)
        provider = _FakeNdviProvider()

        run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        assert not _has_reading_for(session, talhao.id)
        session.rollback()


def test_one_talhao_failure_does_not_abort_the_others() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        failing_boundary = json.dumps(
            {
                "type": "Polygon",
                "coordinates": [[[-48.0, -21.0], [-47.9, -21.0], [-47.9, -20.9], [-48.0, -21.0]]],
            }
        )
        failing_talhao = _make_talhao(session, farm, boundary_geojson=failing_boundary)
        ok_talhao = _make_talhao(session, farm, boundary_geojson=_BOUNDARY)
        provider = _FakeNdviProvider(fail_for_boundary=failing_boundary)

        run_ndvi_pipeline_cycle(session, settings=_enabled_settings(), provider=provider)

        assert not _has_reading_for(session, failing_talhao.id)
        assert _has_reading_for(session, ok_talhao.id)
        session.rollback()
