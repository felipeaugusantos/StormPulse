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

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import workers.tasks as tasks_module
from workers.agro_pipeline import AgroCycleSummary
from workers.lightning_pipeline import LightningCycleSummary
from workers.notification_pipeline import NotificationDeliverySummary
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

    assert result == {
        "frames": 1,
        "cells": 2,
        "risks": 3,
        "alerts": 4,
        "suppressed": 0,
        "ai_summaries_queued": 0,
    }


def test_run_ingestion_cycle_task_dispatches_ai_summaries_after_commit(
    monkeypatch: Any,
) -> None:
    """`session_scope()` here commits (or would, against a real DB) before
    this `with` block exits — the dispatch loop must run only after that,
    never from inside `run_ingestion_cycle` itself (ADR-0060: dispatching
    before commit races the AI summary task's own, separate DB session)."""
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_ingestion_cycle",
        lambda session: CycleSummary(
            frames=1, cells=1, risks=2, alerts=0, risk_ids_for_ai_summary=["a", "b"]
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(tasks_module.generate_risk_ai_summary_task, "delay", dispatched.append)

    result = tasks_module.run_ingestion_cycle_task()

    assert dispatched == ["a", "b"]
    assert result["ai_summaries_queued"] == 2


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


def test_run_notification_delivery_task_returns_summary_dict(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_notification_delivery_cycle",
        lambda session: NotificationDeliverySummary(
            configured=True, attempted=4, sent=2, failed=1, suppressed=1
        ),
    )

    result = tasks_module.run_notification_delivery_task()

    assert result == {
        "configured": True,
        "attempted": 4,
        "sent": 2,
        "failed": 1,
        "suppressed": 1,
    }


def test_run_notification_delivery_task_reports_unconfigured(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_notification_delivery_cycle",
        lambda session: NotificationDeliverySummary(configured=False),
    )

    result = tasks_module.run_notification_delivery_task()

    assert result["configured"] is False
    assert result["attempted"] == 0


def test_run_lightning_detection_task_returns_summary_dict(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_lightning_detection_cycle",
        lambda session: LightningCycleSummary(enabled=True, points_fetched=12, points_active=40),
    )

    result = tasks_module.run_lightning_detection_task()

    assert result == {"enabled": True, "points_fetched": 12, "points_active": 40}


def test_run_lightning_detection_task_reports_disabled(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        tasks_module,
        "run_lightning_detection_cycle",
        lambda session: LightningCycleSummary(enabled=False),
    )

    result = tasks_module.run_lightning_detection_task()

    assert result["enabled"] is False
    assert result["points_fetched"] == 0


class _FakeSessionWithRisk:
    def __init__(self, risk: Any) -> None:
        self._risk = risk

    def get(self, model: Any, risk_id: Any) -> Any:
        return self._risk


def _session_scope_yielding(risk: Any) -> Any:
    @contextmanager
    def _scope() -> Any:
        yield _FakeSessionWithRisk(risk)

    return _scope


def test_generate_risk_ai_summary_task_saves_the_summary(monkeypatch: Any) -> None:
    risk = SimpleNamespace(id=uuid.uuid4(), ai_summary=None)
    monkeypatch.setattr(tasks_module, "session_scope", _session_scope_yielding(risk))
    monkeypatch.setattr(
        tasks_module, "generate_summary", lambda r, settings: "Risco alto de granizo."
    )

    result = tasks_module.generate_risk_ai_summary_task(str(risk.id))

    assert result == {"risk_id": str(risk.id), "generated": True}
    assert risk.ai_summary == "Risco alto de granizo."


def test_generate_risk_ai_summary_task_handles_missing_risk(monkeypatch: Any) -> None:
    monkeypatch.setattr(tasks_module, "session_scope", _session_scope_yielding(None))

    result = tasks_module.generate_risk_ai_summary_task(str(uuid.uuid4()))

    assert result["generated"] is False
    assert result["reason"] == "risk_not_found"


def test_generate_risk_ai_summary_task_handles_unconfigured_or_failed(monkeypatch: Any) -> None:
    risk = SimpleNamespace(id=uuid.uuid4(), ai_summary=None)
    monkeypatch.setattr(tasks_module, "session_scope", _session_scope_yielding(risk))
    monkeypatch.setattr(tasks_module, "generate_summary", lambda r, settings: None)

    result = tasks_module.generate_risk_ai_summary_task(str(risk.id))

    assert result["generated"] is False
    assert result["reason"] == "unconfigured_or_failed"
    assert risk.ai_summary is None
