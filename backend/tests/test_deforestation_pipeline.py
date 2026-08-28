"""Tests for the deforestation-check pipeline (item DETER).

Same pattern as ``test_ndvi_pipeline.py``: tenant/user/location(s) built
directly in the sync session and rolled back at the end, never committed.
A small fake ``DeforestationProvider`` stands in for INPE so this exercises
only the pipeline's own decision logic (eligibility, per-source
persistence, "never overwrite a failed source's last good result"), never
a real network call.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import blind_index
from app.deforestation.models import DeforestationCheck
from app.deforestation.provider import (
    DETER_AMZ_SOURCE,
    PRODES_CERRADO_SOURCE,
    DeforestationAlert,
    DeforestationCheckResult,
    DeforestationProvider,
)
from app.locations.models import Location
from app.tenants.models import Tenant
from app.users.models import User
from workers.db import session_scope
from workers.deforestation_pipeline import run_deforestation_check_cycle

pytestmark = pytest.mark.integration

_BOUNDARY = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [[[-47.81, -21.18], [-47.80, -21.18], [-47.80, -21.17], [-47.81, -21.18]]],
    }
)


def _enabled_settings() -> Settings:
    return Settings(environment="test", deforestation_check_enabled=True)


class _FakeDeforestationProvider(DeforestationProvider):
    def __init__(
        self,
        *,
        result: DeforestationCheckResult | None = None,
        unavailable: list[str] | None = None,
    ) -> None:
        self._result = result
        self._unavailable = unavailable or []

    @property
    def name(self) -> str:
        return "FAKE"

    async def check(
        self, boundary_geojson: str, *, lookback_years: float
    ) -> DeforestationCheckResult:
        if self._result is not None:
            return self._result
        checked = [
            s for s in (DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE) if s not in self._unavailable
        ]
        return DeforestationCheckResult(
            checked_sources=checked, unavailable_sources=self._unavailable, alerts=[]
        )


def _make_farm(session: Session) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"deforest-{unique}@example.com"
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


def _checks_for(session: Session, location_id: object) -> list[DeforestationCheck]:
    return list(
        session.scalars(
            select(DeforestationCheck).where(DeforestationCheck.location_id == location_id)
        ).all()
    )


def test_disabled_by_default_is_a_noop() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", deforestation_check_enabled=False)
        summary = run_deforestation_check_cycle(session, settings=settings)
        assert summary.enabled is False
        assert summary.talhoes_checked == 0
        session.rollback()


def test_both_sources_persisted_on_a_clean_check() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)

        summary = run_deforestation_check_cycle(
            session, settings=_enabled_settings(), provider=_FakeDeforestationProvider()
        )

        assert summary.enabled is True
        checks = _checks_for(session, talhao.id)
        assert {c.source for c in checks} == {DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE}
        assert all(c.alert_count == 0 for c in checks)
        session.rollback()


def test_alerts_are_persisted_per_source() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)
        alert = DeforestationAlert(
            source=DETER_AMZ_SOURCE,
            classname="DESMATAMENTO_CR",
            detected_at=None,
            area_ha=12.5,
            municipio="obidos",
            uf="PA",
        )
        result = DeforestationCheckResult(
            checked_sources=[DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE],
            unavailable_sources=[],
            alerts=[alert],
        )

        run_deforestation_check_cycle(
            session,
            settings=_enabled_settings(),
            provider=_FakeDeforestationProvider(result=result),
        )

        deter_check = next(
            c for c in _checks_for(session, talhao.id) if c.source == DETER_AMZ_SOURCE
        )
        assert deter_check.alert_count == 1
        stored = json.loads(deter_check.alerts_json)
        assert stored[0]["classname"] == "DESMATAMENTO_CR"
        prodes_check = next(
            c for c in _checks_for(session, talhao.id) if c.source == PRODES_CERRADO_SOURCE
        )
        assert prodes_check.alert_count == 0
        session.rollback()


def test_a_failed_source_never_overwrites_its_last_good_result() -> None:
    """DETER-AMZ succeeding then failing on a later cycle must leave its
    previously-stored row untouched — never silently reset to "no alerts"
    just because that cycle's request didn't complete."""
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm)
        alert = DeforestationAlert(
            source=DETER_AMZ_SOURCE,
            classname="DESMATAMENTO_CR",
            detected_at=None,
            area_ha=5.0,
            municipio=None,
            uf="PA",
        )
        first_result = DeforestationCheckResult(
            checked_sources=[DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE],
            unavailable_sources=[],
            alerts=[alert],
        )
        run_deforestation_check_cycle(
            session,
            settings=_enabled_settings(),
            provider=_FakeDeforestationProvider(result=first_result),
        )
        first_checked_at = next(
            c.checked_at for c in _checks_for(session, talhao.id) if c.source == DETER_AMZ_SOURCE
        )

        run_deforestation_check_cycle(
            session,
            settings=_enabled_settings(),
            provider=_FakeDeforestationProvider(unavailable=[DETER_AMZ_SOURCE]),
        )

        deter_check = next(
            c for c in _checks_for(session, talhao.id) if c.source == DETER_AMZ_SOURCE
        )
        assert deter_check.alert_count == 1  # untouched from the first cycle
        assert deter_check.checked_at == first_checked_at
        prodes_check = next(
            c for c in _checks_for(session, talhao.id) if c.source == PRODES_CERRADO_SOURCE
        )
        assert prodes_check.checked_at > first_checked_at  # this one did update
        session.rollback()


def test_farm_without_boundary_is_never_checked() -> None:
    with session_scope() as session:
        farm = _make_farm(session)

        run_deforestation_check_cycle(
            session, settings=_enabled_settings(), provider=_FakeDeforestationProvider()
        )

        assert _checks_for(session, farm.id) == []
        session.rollback()


def test_talhao_without_boundary_is_never_checked() -> None:
    with session_scope() as session:
        farm = _make_farm(session)
        talhao = _make_talhao(session, farm, boundary_geojson=None)

        run_deforestation_check_cycle(
            session, settings=_enabled_settings(), provider=_FakeDeforestationProvider()
        )

        assert _checks_for(session, talhao.id) == []
        session.rollback()
