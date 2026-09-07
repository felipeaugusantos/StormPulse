"""Custom alert rule endpoints (Fase 3 — Alertas Personalizados, ADR-0086).

Ownership is checked directly against ``user_id``/``tenant_id`` on each
row — RLS (the same policy every other tenant-scoped table gets) is the
isolation backstop, this is the explicit "and it's *your* rule, not just
your tenant's" check, same convention as ``app/locations/router.py``'s
``_get_owned_or_404``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alert_rules.models import (
    AlertChannel,
    AlertCondition,
    AlertEscalation,
    AlertEvent,
    AlertRecipient,
    AlertRule,
)
from app.alert_rules.schemas import (
    AcknowledgeIn,
    AlertChannelIn,
    AlertChannelOut,
    AlertConditionOut,
    AlertEscalationIn,
    AlertEscalationOut,
    AlertEventOut,
    AlertRecipientIn,
    AlertRecipientOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    SimulateResult,
)
from app.api.deps import get_current_user, get_db, get_request_settings
from app.core.config import Settings
from app.core.crypto import encrypt_field
from app.core.rls import set_tenant_context
from app.locations.models import Location
from app.users.models import User
from engine.alert_rules import AlertCondition as EngineCondition
from engine.alert_rules import matching_groups
from workers.alert_rules_pipeline import acknowledge_event as pipeline_acknowledge_event
from workers.alert_rules_pipeline import gather_metric_snapshot

router = APIRouter(tags=["alert-rules"])


async def _get_rule_or_404(session: AsyncSession, user: User, rule_id: uuid.UUID) -> AlertRule:
    rule = (
        await session.execute(
            select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user.id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada")
    return rule


def _condition_out(row: AlertCondition) -> AlertConditionOut:
    return AlertConditionOut(
        id=row.id,
        metric=row.metric,
        operator=row.operator,
        threshold=row.threshold,
        group=row.group_index,
    )


async def _rule_out(session: AsyncSession, rule: AlertRule) -> AlertRuleOut:
    conditions = (
        (await session.execute(select(AlertCondition).where(AlertCondition.rule_id == rule.id)))
        .scalars()
        .all()
    )
    return AlertRuleOut(
        id=rule.id,
        location_id=rule.location_id,
        name=rule.name,
        enabled=rule.enabled,
        lead_time_minutes=rule.lead_time_minutes,
        quiet_hours_start=rule.quiet_hours_start,
        quiet_hours_end=rule.quiet_hours_end,
        cooldown_minutes=rule.cooldown_minutes,
        last_fired_at=rule.last_fired_at,
        conditions=[_condition_out(c) for c in conditions],
    )


@router.get("", response_model=list[AlertRuleOut])
async def list_alert_rules(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AlertRuleOut]:
    rules = (
        (await session.execute(select(AlertRule).where(AlertRule.user_id == user.id)))
        .scalars()
        .all()
    )
    return [await _rule_out(session, r) for r in rules]


@router.post("", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    data: AlertRuleCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRuleOut:
    location = (
        await session.execute(
            select(Location).where(Location.id == data.location_id, Location.user_id == user.id)
        )
    ).scalar_one_or_none()
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")

    rule = AlertRule(
        tenant_id=user.tenant_id,
        location_id=data.location_id,
        user_id=user.id,
        name=data.name,
        enabled=data.enabled,
        lead_time_minutes=data.lead_time_minutes,
        quiet_hours_start=data.quiet_hours_start,
        quiet_hours_end=data.quiet_hours_end,
        cooldown_minutes=data.cooldown_minutes,
    )
    session.add(rule)
    await session.flush()
    for condition in data.conditions:
        session.add(
            AlertCondition(
                tenant_id=user.tenant_id,
                rule_id=rule.id,
                metric=condition.metric,
                operator=condition.operator,
                threshold=condition.threshold,
                group_index=condition.group,
            )
        )
    await session.commit()
    # commit() ends the transaction get_current_user's app.tenant_id was
    # scoped to (RLS) — re-apply before the post-commit re-fetch in
    # _rule_out, or it silently returns zero conditions (same gotcha
    # documented in app.locations.service.create_location).
    await set_tenant_context(session, user.tenant_id)
    return await _rule_out(session, rule)


@router.get("/{rule_id}", response_model=AlertRuleOut)
async def get_alert_rule(
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRuleOut:
    rule = await _get_rule_or_404(session, user, rule_id)
    return await _rule_out(session, rule)


@router.put("/{rule_id}", response_model=AlertRuleOut)
async def update_alert_rule(
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRuleOut:
    rule = await _get_rule_or_404(session, user, rule_id)
    for field in (
        "name",
        "enabled",
        "lead_time_minutes",
        "quiet_hours_start",
        "quiet_hours_end",
        "cooldown_minutes",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(rule, field, value)

    if data.conditions is not None:
        existing = (
            (await session.execute(select(AlertCondition).where(AlertCondition.rule_id == rule.id)))
            .scalars()
            .all()
        )
        for row in existing:
            await session.delete(row)
        await session.flush()
        for condition in data.conditions:
            session.add(
                AlertCondition(
                    tenant_id=user.tenant_id,
                    rule_id=rule.id,
                    metric=condition.metric,
                    operator=condition.operator,
                    threshold=condition.threshold,
                    group_index=condition.group,
                )
            )
    await session.commit()
    # commit() ends the transaction get_current_user's app.tenant_id was
    # scoped to (RLS) — re-apply before the post-commit re-fetch in
    # _rule_out, or it silently returns zero conditions (same gotcha
    # documented in app.locations.service.create_location).
    await set_tenant_context(session, user.tenant_id)
    return await _rule_out(session, rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    rule = await _get_rule_or_404(session, user, rule_id)
    await session.delete(rule)
    await session.commit()


@router.post("/{rule_id}/simulate", response_model=SimulateResult)
async def simulate_alert_rule(
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> SimulateResult:
    """Runs the exact same condition evaluation the real cycle uses,
    against the location's *current* metric snapshot — never writes an
    AlertEvent/AlertDelivery/Alert (Fase 3's explicit acceptance
    criterion: simulation never sends a real alert)."""
    rule = await _get_rule_or_404(session, user, rule_id)
    location = await session.get(Location, rule.location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")

    conditions_rows = (
        (await session.execute(select(AlertCondition).where(AlertCondition.rule_id == rule.id)))
        .scalars()
        .all()
    )
    engine_conditions = [
        EngineCondition(
            metric=c.metric,  # type: ignore[arg-type]
            operator=c.operator,  # type: ignore[arg-type]
            threshold=c.threshold,
            group=c.group_index,
        )
        for c in conditions_rows
    ]

    # gather_metric_snapshot needs a sync Session (it queries lightning/
    # storm-risk with the sync ORM style used by every other worker
    # pipeline) — this endpoint's own session is async, so a short-lived
    # sync session is opened just for this read-only gather, same "two
    # session types coexist by design" split as forecast_comparison.
    from workers.db import session_scope

    with session_scope() as sync_session:
        sync_location = sync_session.get(type(location), location.id)
        snapshot = await gather_metric_snapshot(sync_location, settings, sync_session)  # type: ignore[arg-type]

    matched = matching_groups(engine_conditions, snapshot)
    return SimulateResult(
        would_fire=bool(matched),
        snapshot={
            "rain_mm": snapshot.rain_mm,
            "rain_probability_percent": snapshot.rain_probability_percent,
            "wind_kmh": snapshot.wind_kmh,
            "temperature_c": snapshot.temperature_c,
            "frost_temperature_c": snapshot.frost_temperature_c,
            "vpd_kpa": snapshot.vpd_kpa,
            "soil_moisture_percent": snapshot.soil_moisture_percent,
            "disease_risk_high": snapshot.disease_risk_high,
            "lightning_distance_km": snapshot.lightning_distance_km,
            "storm_eta_minutes": snapshot.storm_eta_minutes,
        },
        matched_groups=matched,
    )


@router.get("/{rule_id}/events", response_model=list[AlertEventOut])
async def list_alert_rule_events(
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AlertEventOut]:
    await _get_rule_or_404(session, user, rule_id)
    from app.alert_rules.models import AlertAcknowledgement

    events = (
        (
            await session.execute(
                select(AlertEvent)
                .where(AlertEvent.rule_id == rule_id)
                .order_by(AlertEvent.opened_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for event in events:
        acked = (
            await session.execute(
                select(AlertAcknowledgement).where(AlertAcknowledgement.event_id == event.id)
            )
        ).scalar_one_or_none()
        out.append(
            AlertEventOut(
                id=event.id,
                rule_id=event.rule_id,
                location_id=event.location_id,
                alert_id=event.alert_id,
                status=event.status,
                opened_at=event.opened_at,
                last_updated_at=event.last_updated_at,
                closed_at=event.closed_at,
                acknowledged=acked is not None,
            )
        )
    return out


@router.post("/events/{event_id}/acknowledge", response_model=AlertEventOut)
async def acknowledge_alert_event(
    event_id: uuid.UUID,
    data: AcknowledgeIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertEventOut:
    event = await session.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado")
    rule = await session.get(AlertRule, event.rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado")

    from workers.db import session_scope

    with session_scope() as sync_session:
        pipeline_acknowledge_event(
            sync_session, event_id=event.id, user_id=user.id, notes=data.notes
        )

    return AlertEventOut(
        id=event.id,
        rule_id=event.rule_id,
        location_id=event.location_id,
        alert_id=event.alert_id,
        status=event.status,
        opened_at=event.opened_at,
        last_updated_at=event.last_updated_at,
        closed_at=event.closed_at,
        acknowledged=True,
    )


# ---------------------------------------------------------------------------
# Channels (tenant-wide, reusable across rules)
# ---------------------------------------------------------------------------

channels_router = APIRouter(tags=["alert-rules"])


def _channel_out(row: AlertChannel) -> AlertChannelOut:
    return AlertChannelOut(
        id=row.id,
        kind=row.kind,
        name=row.name,
        enabled=row.enabled,
        webhook_url=row.webhook_url,
        phone_number=row.phone_number,
        has_webhook_secret=row.webhook_secret_encrypted is not None,
    )


@channels_router.get("", response_model=list[AlertChannelOut])
async def list_alert_channels(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AlertChannelOut]:
    rows = (
        (
            await session.execute(
                select(AlertChannel).where(AlertChannel.tenant_id == user.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    return [_channel_out(r) for r in rows]


@channels_router.post("", response_model=AlertChannelOut, status_code=status.HTTP_201_CREATED)
async def create_alert_channel(
    data: AlertChannelIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertChannelOut:
    channel = AlertChannel(
        tenant_id=user.tenant_id,
        kind=data.kind,
        name=data.name,
        enabled=data.enabled,
        webhook_url=data.webhook_url,
        webhook_secret_encrypted=encrypt_field(data.webhook_secret)
        if data.webhook_secret
        else None,
        phone_number=data.phone_number,
    )
    session.add(channel)
    await session.commit()
    return _channel_out(channel)


@channels_router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_channel(
    channel_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    channel = (
        await session.execute(
            select(AlertChannel).where(
                AlertChannel.id == channel_id, AlertChannel.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal não encontrado")
    await session.delete(channel)
    await session.commit()


# ---------------------------------------------------------------------------
# Recipients + escalation steps (nested under a rule)
# ---------------------------------------------------------------------------


@router.post(
    "/{rule_id}/recipients", response_model=AlertRecipientOut, status_code=status.HTTP_201_CREATED
)
async def add_alert_recipient(
    rule_id: uuid.UUID,
    data: AlertRecipientIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRecipientOut:
    rule = await _get_rule_or_404(session, user, rule_id)
    channel = (
        await session.execute(
            select(AlertChannel).where(
                AlertChannel.id == data.channel_id, AlertChannel.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Canal não encontrado")
    recipient = AlertRecipient(
        tenant_id=user.tenant_id,
        rule_id=rule.id,
        channel_id=data.channel_id,
        user_id=data.user_id,
        enabled=data.enabled,
    )
    session.add(recipient)
    await session.commit()
    return AlertRecipientOut(
        id=recipient.id,
        channel_id=recipient.channel_id,
        user_id=recipient.user_id,
        enabled=recipient.enabled,
    )


@router.delete("/recipients/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_recipient(
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    recipient = await session.get(AlertRecipient, recipient_id)
    if recipient is None or recipient.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Destinatário não encontrado"
        )
    await session.delete(recipient)
    await session.commit()


@router.post(
    "/{rule_id}/escalations", response_model=AlertEscalationOut, status_code=status.HTTP_201_CREATED
)
async def add_alert_escalation(
    rule_id: uuid.UUID,
    data: AlertEscalationIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertEscalationOut:
    rule = await _get_rule_or_404(session, user, rule_id)
    recipient = await session.get(AlertRecipient, data.recipient_id)
    if recipient is None or recipient.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Destinatário não encontrado"
        )
    escalation = AlertEscalation(
        tenant_id=user.tenant_id,
        rule_id=rule.id,
        step_order=data.step_order,
        delay_minutes=data.delay_minutes,
        recipient_id=data.recipient_id,
        enabled=data.enabled,
    )
    session.add(escalation)
    await session.commit()
    return AlertEscalationOut(
        id=escalation.id,
        step_order=escalation.step_order,
        delay_minutes=escalation.delay_minutes,
        recipient_id=escalation.recipient_id,
        enabled=escalation.enabled,
    )
