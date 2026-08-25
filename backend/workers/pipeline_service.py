"""Ingestion → engine → risk → alert pipeline (FASE 10).

Runs one cycle synchronously: pull frames from the active weather provider,
run the storm engine, persist cells/tracks/observations, then for each active
monitored location compute risk, persist it, and (idempotently) emit alerts and
queue notifications.

⚠️ With the MOCK provider every persisted row is simulated (``is_mock=True``);
values are never presented as real observations. Cross-cycle tracking is
simplistic here (alerts compare consecutive risk computations per location) —
adequate for the MVP and explicitly replaceable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.engine import AlertEngine, AlertState, active_hazards
from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import NotificationChannel, NotificationStatus
from app.core.thresholds import AlertPolicy
from app.locations.models import Location
from app.notifications.models import Notification
from app.storms.models import StormCell, StormObservation, StormRisk, StormTrack
from app.weather.factory import get_weather_provider
from app.weather.provider import RadarFrameData, WeatherProvider
from engine.geo import haversine_km
from engine.pipeline import StormEngine, TrackedStorm
from engine.provider_types import FrameInput, RawCellInput
from engine.risk.engine import RiskAssessment, RiskInput, StormRiskEngine
from engine.trajectory.estimator import eta_minutes_to
from workers.db import bypass_rls


@dataclass
class CycleSummary:
    frames: int
    cells: int
    risks: int
    alerts: int


def _to_frame_inputs(frames: list[RadarFrameData]) -> list[FrameInput]:
    return [
        FrameInput(
            captured_at=f.captured_at,
            is_mock=f.provenance.is_mock,
            raw_cells=[
                RawCellInput(
                    latitude=c.latitude,
                    longitude=c.longitude,
                    max_reflectivity=c.max_reflectivity,
                    average_reflectivity=c.average_reflectivity,
                    area_km2=c.area_km2,
                )
                for c in f.cells
            ],
        )
        for f in frames
    ]


def _point(lat: float, lon: float) -> WKTElement:
    return WKTElement(f"POINT({lon} {lat})", srid=4326)


def _prune_old_mock_cells(session: Session, *, older_than: timedelta) -> None:
    cutoff = datetime.now(UTC) - older_than
    stale = session.scalars(
        select(StormCell).where(StormCell.is_mock.is_(True), StormCell.detected_at < cutoff)
    ).all()
    for cell in stale:
        session.delete(cell)


def _persist_tracked(session: Session, tracked: TrackedStorm) -> StormCell:
    """Persist a tracked storm's current cell, its track and observations."""
    last = tracked.track.last
    cell = StormCell(
        weather_source_id=None,
        detected_at=last.detected_at,
        latitude=last.latitude,
        longitude=last.longitude,
        geometry=WKTElement(last.footprint_wkt, srid=4326) if last.footprint_wkt else None,
        centroid=_point(last.latitude, last.longitude),
        max_reflectivity=last.max_reflectivity,
        average_reflectivity=last.average_reflectivity,
        area_km2=last.area_km2,
        severity=last.severity,
        is_mock=last.is_mock,
    )
    session.add(cell)

    track = StormTrack(
        storm_cell=cell,
        started_at=tracked.track.started_at,
        last_observed_at=tracked.track.last_observed_at,
        is_active=True,
    )
    session.add(track)

    traj = tracked.trajectory
    for i, obs in enumerate(tracked.track.observations):
        is_last = i == len(tracked.track.observations) - 1
        session.add(
            StormObservation(
                track=track,
                observed_at=obs.detected_at,
                latitude=obs.latitude,
                longitude=obs.longitude,
                geom=_point(obs.latitude, obs.longitude),
                speed_kmh=traj.speed_kmh if (is_last and traj) else None,
                direction_deg=traj.direction_deg if (is_last and traj) else None,
                intensity=obs.max_reflectivity,
                trend=traj.trend if (is_last and traj) else None,
            )
        )
    return cell


def _alert_state_from_risk(risk: StormRisk, policy: AlertPolicy) -> AlertState:
    """Reconstruct the comparison state from a previously stored risk row."""
    pseudo = RiskAssessment(
        severity=risk.severity,
        score=0.0,
        rain_risk=risk.rain_risk,
        wind_risk=risk.wind_risk,
        hail_risk=risk.hail_risk,
        lightning_risk=risk.lightning_risk,
        storm_distance_km=risk.storm_distance_km,
        storm_speed_kmh=risk.storm_speed_kmh,
        eta_minutes=risk.eta_minutes,
        is_mock=risk.is_mock,
    )
    return AlertState(
        level=risk.severity,
        eta_minutes=risk.eta_minutes,
        distance_km=risk.storm_distance_km,
        active_hazards=active_hazards(pseudo, policy),
    )


def _nearest(
    location: Location, cells: list[tuple[StormCell, TrackedStorm]]
) -> tuple[StormCell, TrackedStorm, float] | None:
    best: tuple[StormCell, TrackedStorm, float] | None = None
    for cell, tracked in cells:
        d = haversine_km(location.latitude, location.longitude, cell.latitude, cell.longitude)
        if d <= location.radius_km and (best is None or d < best[2]):
            best = (cell, tracked, d)
    return best


def run_ingestion_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: WeatherProvider | None = None,
) -> CycleSummary:
    settings = settings or get_settings()
    provider = provider or get_weather_provider(settings)
    policy = AlertPolicy()

    # Prune stale mock cells *before* fetching frames, and commit right
    # away: when the real provider is down, get_radar_frames raises and
    # session_scope() rolls back the whole transaction — if pruning ran
    # later (or shared this transaction), that rollback would silently
    # undo the cleanup too, and old mock rows from an earlier session
    # would linger on the dashboard indefinitely, looking like live data
    # instead of the stale demo leftovers they are.
    _prune_old_mock_cells(session, older_than=timedelta(hours=2))
    session.commit()
    # commit() ends the transaction session_scope()'s RLS bypass (migration
    # 0b7b9a5dbd11) was scoped to — without this, the `Location` query
    # below silently comes back empty under RLS (no error), and the whole
    # rest of the cycle quietly no-ops.
    bypass_rls(session)

    frames = asyncio.run(provider.get_radar_frames(limit=6))
    tracked_storms = StormEngine().process(_to_frame_inputs(frames))

    persisted: list[tuple[StormCell, TrackedStorm]] = [
        (_persist_tracked(session, tracked), tracked) for tracked in tracked_storms
    ]
    session.flush()  # assign cell ids

    risk_engine = StormRiskEngine()
    alert_engine = AlertEngine(policy)
    risks = 0
    alerts = 0

    locations = session.scalars(select(Location).where(Location.is_active.is_(True))).all()
    for location in locations:
        match = _nearest(location, persisted)
        if match is None:
            continue
        cell, tracked, distance = match

        eta = None
        speed = None
        if tracked.trajectory is not None:
            speed = tracked.trajectory.speed_kmh
            eta = eta_minutes_to(
                tracked.trajectory,
                current_lat=cell.latitude,
                current_lon=cell.longitude,
                target_lat=location.latitude,
                target_lon=location.longitude,
            )

        assessment = risk_engine.assess(
            RiskInput(
                distance_km=distance,
                severity=cell.severity,
                max_reflectivity=cell.max_reflectivity,
                speed_kmh=speed,
                eta_minutes=eta,
                is_mock=cell.is_mock,
            )
        )

        previous_risk = session.scalars(
            select(StormRisk)
            .where(StormRisk.location_id == location.id)
            .order_by(StormRisk.computed_at.desc())
            .limit(1)
        ).first()
        previous_state = _alert_state_from_risk(previous_risk, policy) if previous_risk else None

        session.add(
            StormRisk(
                tenant_id=location.tenant_id,
                location_id=location.id,
                storm_cell_id=cell.id,
                severity=assessment.severity,
                rain_risk=assessment.rain_risk,
                wind_risk=assessment.wind_risk,
                hail_risk=assessment.hail_risk,
                lightning_risk=assessment.lightning_risk,
                storm_distance_km=assessment.storm_distance_km,
                storm_speed_kmh=assessment.storm_speed_kmh,
                eta_minutes=assessment.eta_minutes,
                computed_at=datetime.now(UTC),
                is_mock=assessment.is_mock,
                experimental=assessment.experimental,
                detail=assessment.detail,
            )
        )
        risks += 1

        decision = alert_engine.decide(
            assessment,
            previous_state,
            location_id=str(location.id),
            storm_cell_id=str(cell.id),
        )
        if decision.emit and decision.dedup_key is not None:
            already = session.scalars(
                select(Alert).where(
                    Alert.tenant_id == location.tenant_id,
                    Alert.dedup_key == decision.dedup_key,
                )
            ).first()
            if already is None:
                alert = Alert(
                    tenant_id=location.tenant_id,
                    user_id=location.user_id,
                    location_id=location.id,
                    storm_cell_id=cell.id,
                    event_type=decision.event_type,
                    level=decision.level,
                    title=f"{decision.level.value.upper()}: tempestade próxima de {location.name}",
                    message="; ".join(decision.reasons) or "Condições de risco detectadas.",
                    dedup_key=decision.dedup_key,
                )
                session.add(alert)
                session.flush()
                session.add(
                    Notification(
                        tenant_id=location.tenant_id,
                        alert_id=alert.id,
                        user_id=location.user_id,
                        channel=NotificationChannel.PUSH,
                        status=NotificationStatus.PENDING,
                    )
                )
                alerts += 1

    return CycleSummary(frames=len(frames), cells=len(persisted), risks=risks, alerts=alerts)
