"""Cross-tenant read queries and mutations for the platform-admin panel
(FASE 28, ADR-0048/ADR-0049).

Every mutation writes its own `AdminAuditLog` row in the same transaction
it makes the change in — there is no code path that mutates a user without
also recording who did it and what changed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import AdminAuditLog
from app.admin.schemas import (
    AdminAuditLogOut,
    AdminRawFrameOut,
    AdminStatsOut,
    AdminTenantOut,
    AdminUserOut,
    AdminUserUpdateIn,
    AlertVerificationIn,
    AlertVerificationOut,
    EventTypeMetricsOut,
    PipelineHealthOut,
    ValidationMetricsOut,
)
from app.alerts.models import Alert
from app.alerts.verification_models import AlertVerification
from app.core.enums import UserRole
from app.core.rls import bypass_rls
from app.lightning.models import LightningStrike
from app.locations.models import Location
from app.ndvi.models import NdviReading
from app.satellite.models import SatelliteImage
from app.storms.models import StormCell, StormRisk
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.models import RadarFrame
from engine.validation import EtaSample, PredictionOutcome, mean_absolute_eta_error_minutes
from engine.validation import precision_recall as _precision_recall

MAX_PAGE_SIZE = 200

# Only these two roles are actually implemented today (METEOROLOGIST/
# COMPANY_ADMIN/OPERATOR are reserved for later phases, per
# app/core/enums.py) — granting a role nothing in the app understands yet
# would be a silent no-op dressed up as a real permission change.
ALLOWED_ROLE_CHANGES = {UserRole.USER, UserRole.ADMIN}


class UserNotFound(Exception):
    """The target `user_id` doesn't exist."""


class NoChangesRequested(Exception):
    """Neither `is_active` nor `role` was set on the update."""


class UnsupportedRole(Exception):
    """The requested role isn't one of ALLOWED_ROLE_CHANGES."""

    def __init__(self, role: UserRole) -> None:
        self.role = role


class SelfLockoutAttempt(Exception):
    """An operator tried to deactivate their own account."""


async def list_users(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[AdminUserOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    stmt = select(User, Tenant.name).join(Tenant, Tenant.id == User.tenant_id)
    stmt = stmt.order_by(User.created_at.desc())

    rows: Sequence[tuple[User, str]]
    if search:
        # email/full_name are encrypted at rest (ADR-0055) — a random AES-GCM
        # nonce per row means the ciphertext can never be filtered with SQL
        # LIKE, so this decrypts (via the ORM's transparent EncryptedString)
        # and filters in Python instead, then paginates the filtered list.
        # Acceptable at this platform's admin-panel scale; would need a
        # dedicated search index if the user base grew far larger.
        needle = search.lower()
        all_rows = (await session.execute(stmt)).all()
        matched = [
            (user, tenant_name)
            for user, tenant_name in all_rows
            if needle in user.email.lower() or (user.full_name and needle in user.full_name.lower())
        ]
        total = len(matched)
        rows = matched[offset : offset + limit]
    else:
        total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        rows = [
            (user, tenant_name)
            for user, tenant_name in (await session.execute(stmt.limit(limit).offset(offset))).all()
        ]

    items = [
        AdminUserOut(
            id=user.id,
            tenant_id=user.tenant_id,
            tenant_name=tenant_name,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_platform_admin=user.is_platform_admin,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
        for user, tenant_name in rows
    ]
    return items, total


async def list_tenants(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[AdminTenantOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    user_counts = (
        select(User.tenant_id, func.count().label("user_count")).group_by(User.tenant_id).subquery()
    )
    location_counts = (
        select(Location.tenant_id, func.count().label("location_count"))
        .group_by(Location.tenant_id)
        .subquery()
    )
    stmt = (
        select(
            Tenant,
            func.coalesce(user_counts.c.user_count, 0),
            func.coalesce(location_counts.c.location_count, 0),
        )
        .outerjoin(user_counts, user_counts.c.tenant_id == Tenant.id)
        .outerjoin(location_counts, location_counts.c.tenant_id == Tenant.id)
    )
    count_stmt = select(func.count()).select_from(Tenant)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(Tenant.name).like(pattern))
        count_stmt = count_stmt.where(func.lower(Tenant.name).like(pattern))

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [
        AdminTenantOut(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            user_count=user_count,
            location_count=location_count,
        )
        for tenant, user_count, location_count in rows
    ]
    return items, total


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> AdminUserOut | None:
    stmt = (
        select(User, Tenant.name)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == user_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    user, tenant_name = row
    return AdminUserOut(
        id=user.id,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _log(*, actor: User, action: str, target: User, detail: dict[str, object]) -> AdminAuditLog:
    return AdminAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_user_id=target.id,
        target_email=target.email,
        detail=detail,
    )


async def update_user(
    session: AsyncSession, *, actor: User, target_user_id: uuid.UUID, data: AdminUserUpdateIn
) -> AdminUserOut:
    """Applies `is_active`/`role` changes and writes one audit log row per
    field that actually changed value (a no-op field — e.g. re-sending the
    role it already has — writes nothing, since nothing happened)."""
    if data.is_active is None and data.role is None:
        raise NoChangesRequested
    if data.role is not None and data.role not in ALLOWED_ROLE_CHANGES:
        raise UnsupportedRole(data.role)

    target = await session.get(User, target_user_id)
    if target is None:
        raise UserNotFound(target_user_id)

    if data.is_active is False and target.id == actor.id:
        raise SelfLockoutAttempt

    if data.is_active is not None and data.is_active != target.is_active:
        session.add(
            _log(
                actor=actor,
                action="user.activate" if data.is_active else "user.deactivate",
                target=target,
                detail={"is_active": {"from": target.is_active, "to": data.is_active}},
            )
        )
        target.is_active = data.is_active

    if data.role is not None and data.role != target.role:
        session.add(
            _log(
                actor=actor,
                action="user.role_change",
                target=target,
                detail={"role": {"from": target.role.value, "to": data.role.value}},
            )
        )
        target.role = data.role

    await session.commit()
    # commit() ends the transaction require_platform_admin's bypass was
    # scoped to (RLS, migration 0b7b9a5dbd11) — re-apply before the
    # post-commit re-fetch, which is legitimately cross-tenant (target may
    # belong to a different tenant than the acting admin).
    await bypass_rls(session)

    updated = await get_user(session, target_user_id)
    assert updated is not None  # the row we just updated can't have vanished
    return updated


async def list_audit_log(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[AdminAuditLogOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    total = (await session.execute(select(func.count()).select_from(AdminAuditLog))).scalar_one()
    stmt = (
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [AdminAuditLogOut.model_validate(row) for row in rows]
    return items, total


async def list_raw_frames(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[AdminRawFrameOut], int]:
    """Item 4, ADR-0065 — raw radar frames retained per ingestion cycle,
    exactly as the active provider returned them."""
    limit = min(limit, MAX_PAGE_SIZE)
    total = (await session.execute(select(func.count()).select_from(RadarFrame))).scalar_one()
    stmt = select(RadarFrame).order_by(RadarFrame.captured_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    items = [AdminRawFrameOut.model_validate(row) for row in rows]
    return items, total


async def get_stats(session: AsyncSession) -> AdminStatsOut:
    now = datetime.now(UTC)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    total_tenants = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    active_users_7d = (
        await session.execute(
            select(func.count()).select_from(User).where(User.last_login_at >= cutoff_7d)
        )
    ).scalar_one()
    active_users_30d = (
        await session.execute(
            select(func.count()).select_from(User).where(User.last_login_at >= cutoff_30d)
        )
    ).scalar_one()
    total_locations = (
        await session.execute(select(func.count()).select_from(Location))
    ).scalar_one()
    alerts_last_30d = (
        await session.execute(
            select(func.count()).select_from(Alert).where(Alert.created_at >= cutoff_30d)
        )
    ).scalar_one()

    return AdminStatsOut(
        total_tenants=total_tenants,
        total_users=total_users,
        active_users_7d=active_users_7d,
        active_users_30d=active_users_30d,
        total_locations=total_locations,
        alerts_last_30d=alerts_last_30d,
    )


# (name, expected interval seconds, staleness threshold seconds) — the
# interval must match the actual Celery beat schedule in
# workers/celery_app.py (kept here rather than importing that module,
# since workers/ isn't a dependency of app/). The staleness threshold is
# NOT always a flat 2x the interval: `satellite`'s `captured_at` is the
# GOES scene's own true scan time (from STAC item metadata, see
# `_persist_image(..., now=timestamp)` in workers/satellite_pipeline.py —
# NOT when our own cycle ran), and the real gap between a GOES scan and
# that scene actually being published/available commonly runs 20-40+
# minutes on its own, independent of anything on our side. A 2x-interval
# (20 min) threshold there would flag "atrasado" on every single healthy
# cycle — confirmed live in production (FASE 34 follow-up) chasing exactly
# that false alarm before finding the real explanation. `ndvi`'s own
# threshold is looser still (3 days, nowhere near 2x its own 8h cycle)
# for a different reason than the cycle's own cadence: Sentinel-2 only
# revisits a given talhão every ~5 days, and a cloudy pass yields no
# usable pixels at all (see SentinelHubNdviProvider) — a talhão-by-talhão
# gap that long is normal, not a stuck pipeline.
_PIPELINE_THRESHOLDS: tuple[tuple[str, int, int], ...] = (
    ("satellite", 600, 3600),  # satellite-detect-every-10-minutes
    ("storms", 300, 600),  # ingest-every-5-minutes
    ("lightning", 300, 600),  # lightning-detect-every-5-minutes
    ("ndvi", 28_800, 259_200),  # ndvi-check-every-8-hours
)


async def get_pipeline_health(session: AsyncSession) -> list[PipelineHealthOut]:
    """Freshness of each background pipeline's most recent data.

    ``last_updated_at`` is the latest row's own timestamp, not a separate
    "the cron last fired" record — there's no such log kept. For
    ``storms``/``lightning`` it's when our own cycle wrote the row, so a
    stale reading can mean either a stuck pipeline or genuinely quiet
    weather — worth checking manually, not a hard failure signal on its
    own. For ``satellite`` it's the GOES scene's true scan time (see
    ``_PIPELINE_THRESHOLDS`` above for why its staleness threshold is much
    looser, not because our cycle runs less reliably). For ``ndvi`` it's
    the freshest reading across *every* tenant's talhões — genuinely
    absent (``stale`` with ``last_updated_at=None``) when no talhão has a
    drawn boundary yet, or when ``NDVI_ENABLED=false``, not a failure.
    """
    now = datetime.now(UTC)
    latest_by_table = {
        "satellite": (
            await session.execute(select(func.max(SatelliteImage.captured_at)))
        ).scalar_one(),
        "storms": (await session.execute(select(func.max(StormCell.created_at)))).scalar_one(),
        "lightning": (
            await session.execute(select(func.max(LightningStrike.created_at)))
        ).scalar_one(),
        "ndvi": (await session.execute(select(func.max(NdviReading.observed_at)))).scalar_one(),
    }

    results = []
    for name, interval_seconds, staleness_seconds in _PIPELINE_THRESHOLDS:
        last = latest_by_table[name]
        stale = last is None or (now - last) > timedelta(seconds=staleness_seconds)
        results.append(
            PipelineHealthOut(
                name=name,
                last_updated_at=last,
                expected_interval_seconds=interval_seconds,
                stale=stale,
            )
        )
    return results


class AlertNotFound(Exception):
    """The target `alert_id` doesn't exist."""


# ADR-0036 flagged a minimum-sample-size gate as needed but left the
# threshold undefined; set here rather than left unenforced.
MIN_VALIDATION_SAMPLE_SIZE = 30


async def upsert_alert_verification(
    session: AsyncSession, *, actor: User, alert_id: uuid.UUID, data: AlertVerificationIn
) -> AlertVerificationOut:
    """Records (or updates) the ground-truth outcome of an already-issued
    `Alert` (ADR-0036/0058) — the only way `AlertVerification` rows get
    populated today; see that model's docstring for why there's no public
    "confirm this alert" endpoint yet."""
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise AlertNotFound(alert_id)

    existing = (
        await session.execute(
            select(AlertVerification).where(AlertVerification.alert_id == alert_id)
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is None:
        existing = AlertVerification(alert_id=alert_id, tenant_id=alert.tenant_id)
        session.add(existing)

    existing.confirmed = data.confirmed
    existing.actual_arrival_at = data.actual_arrival_at
    existing.notes = data.notes
    existing.confidence = data.confidence
    existing.verified_by = actor.id
    existing.verified_at = now

    await session.commit()
    # commit() ends the transaction require_platform_admin's bypass was
    # scoped to (RLS, migration 0b7b9a5dbd11) — re-apply before the
    # post-commit refresh, same reasoning as update_user() above.
    await bypass_rls(session)
    await session.refresh(existing)
    return AlertVerificationOut.model_validate(existing)


async def get_validation_metrics(session: AsyncSession) -> ValidationMetricsOut:
    """Real backtesting metrics computed from `AlertVerification` rows an
    operator actually recorded — never simulated data (ADR-0036/0058). See
    `ValidationMetricsOut`'s docstring for why only a confirmation rate
    (not recall) is reported.
    """
    rows = (
        await session.execute(
            select(Alert.event_type, AlertVerification, StormRisk)
            .join(AlertVerification, AlertVerification.alert_id == Alert.id)
            .outerjoin(StormRisk, StormRisk.id == Alert.storm_risk_id)
            .where(AlertVerification.confirmed.is_not(None))
        )
    ).all()

    outcomes_by_type: dict[str, list[PredictionOutcome]] = {}
    eta_samples: list[EtaSample] = []
    for event_type, verification, storm_risk in rows:
        event_type_value = event_type.value if hasattr(event_type, "value") else str(event_type)
        outcomes_by_type.setdefault(event_type_value, []).append(
            PredictionOutcome(
                event_type=event_type_value,
                predicted=True,
                observed=bool(verification.confirmed),
            )
        )
        if (
            verification.confirmed
            and verification.actual_arrival_at is not None
            and storm_risk is not None
            and storm_risk.eta_minutes is not None
        ):
            predicted_arrival = storm_risk.computed_at + timedelta(minutes=storm_risk.eta_minutes)
            eta_samples.append(
                EtaSample(
                    predicted_arrival=predicted_arrival,
                    actual_arrival=verification.actual_arrival_at,
                )
            )

    all_outcomes = [o for outcomes in outcomes_by_type.values() for o in outcomes]
    overall = _precision_recall(all_outcomes)
    by_event_type = {
        event_type: EventTypeMetricsOut(
            sample_size=len(outcomes),
            confirmed_count=sum(1 for o in outcomes if o.observed),
            confirmation_rate=_precision_recall(outcomes).precision,
        )
        for event_type, outcomes in outcomes_by_type.items()
    }

    sample_size = len(all_outcomes)
    return ValidationMetricsOut(
        sample_size=sample_size,
        confirmed_count=overall.true_positives,
        confirmation_rate=overall.precision,
        by_event_type=by_event_type,
        eta_sample_size=len(eta_samples),
        mean_absolute_eta_error_minutes=mean_absolute_eta_error_minutes(eta_samples),
        min_sample_size=MIN_VALIDATION_SAMPLE_SIZE,
        reliable=sample_size >= MIN_VALIDATION_SAMPLE_SIZE,
    )
