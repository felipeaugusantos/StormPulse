"""Tests for raw radar-frame retention (item 4, ADR-0065).

Needs real Postgres — same pattern as test_integration_pipeline.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.weather.mock import MockWeatherProvider
from app.weather.models import RadarFrame, WeatherSource
from workers.db import session_scope
from workers.pipeline_service import run_ingestion_cycle

pytestmark = pytest.mark.integration


def test_ingestion_cycle_persists_raw_frames_with_cell_data() -> None:
    with session_scope() as session:
        before = session.scalars(select(RadarFrame)).all()
        before_ids = {f.id for f in before}

        run_ingestion_cycle(session, provider=MockWeatherProvider())

        after = session.scalars(select(RadarFrame)).all()
        new_frames = [f for f in after if f.id not in before_ids]
        assert len(new_frames) >= 1
        frame = new_frames[0]
        assert frame.is_mock is True
        assert "cells" in frame.meta
        assert isinstance(frame.meta["cells"], list)
        session.rollback()


def test_weather_source_is_reused_not_duplicated() -> None:
    with session_scope() as session:
        run_ingestion_cycle(session, provider=MockWeatherProvider())
        run_ingestion_cycle(session, provider=MockWeatherProvider())

        sources = session.scalars(
            select(WeatherSource).where(WeatherSource.name == MockWeatherProvider().name)
        ).all()
        assert len(sources) == 1
        session.rollback()


def test_old_raw_frames_are_pruned_past_retention_window() -> None:
    with session_scope() as session:
        run_ingestion_cycle(session, provider=MockWeatherProvider())
        source = session.scalars(
            select(WeatherSource).where(WeatherSource.name == MockWeatherProvider().name)
        ).one()

        stale = RadarFrame(
            weather_source_id=source.id,
            captured_at=datetime.now(UTC) - timedelta(days=999),
            is_mock=True,
            meta={"cells": []},
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id

        run_ingestion_cycle(
            session,
            settings=Settings(environment="test", raw_frame_retention_days=30),
            provider=MockWeatherProvider(),
        )

        remaining = session.get(RadarFrame, stale_id)
        assert remaining is None
        session.rollback()
