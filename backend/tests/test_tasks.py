"""Unit tests for the Celery task wrappers (``workers/tasks.py``).

No real Postgres/Redis/broker involved: ``session_scope`` and each
underlying ``run_*_cycle`` function are monkeypatched, so these verify only
the tasks' own logic — building the result dict from the cycle summary and
returning it — the same responsibility split already used elsewhere (the
cycle functions themselves are tested in their own
``test_agro_pipeline.py``/``test_satellite_pipeline.py``/
``test_integration_pipeline.py``). Calling a Celery task function directly
(not via ``.delay()``) runs it synchronously in-process, no broker needed —
standard Celery testing practice.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import workers.tasks as tasks_module
from workers.agro_pipeline import AgroCycleSummary
from workers.pipeline_service import CycleSummary
from workers.satellite_pipeline import SatelliteCycleSummary


@contextmanager
def _fake_session_scope() -> Any:
    yield object()


def test_run_ingestion_cycle_task_returns_summary_dict(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_ingestion_cycle",
        lambda session: CycleSummary(frames=1, cells=2, risks=3, alerts=4),
    )

    result = tasks_module.run_ingestion_cycle_task()

    assert result == {"frames": 1, "cells": 2, "risks": 3, "alerts": 4}


def test_run_satellite_detection_task_returns_summary_dict(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_satellite_detection_cycle",
        lambda session: SatelliteCycleSummary(
            enabled=True,
            frames_downloaded=1,
            systems_detected=2,
            watches_active=3,
            watches_dissipated=4,
            alerts=5,
        ),
    )

    result = tasks_module.run_satellite_detection_task()

    assert result == {
        "enabled": True,
        "frames_downloaded": 1,
        "systems_detected": 2,
        "watches_active": 3,
        "watches_dissipated": 4,
        "alerts": 5,
    }


def test_run_satellite_detection_task_reports_disabled(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_satellite_detection_cycle",
        lambda session: SatelliteCycleSummary(enabled=False),
    )

    result = tasks_module.run_satellite_detection_task()

    assert result["enabled"] is False
    assert result["frames_downloaded"] == 0


def test_run_agro_advisory_task_returns_summary_dict(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_agro_advisory_cycle",
        lambda session: AgroCycleSummary(
            enabled=True, locations_checked=10, frost_alerts=1, dry_spell_alerts=2
        ),
    )

    result = tasks_module.run_agro_advisory_task()

    assert result == {
        "enabled": True,
        "locations_checked": 10,
        "frost_alerts": 1,
        "dry_spell_alerts": 2,
    }


def test_run_agro_advisory_task_reports_disabled(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module, "run_agro_advisory_cycle", lambda session: AgroCycleSummary(enabled=False)
    )

    result = tasks_module.run_agro_advisory_task()

    assert result["enabled"] is False
    assert result["locations_checked"] == 0
