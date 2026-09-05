from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import blind_index
from app.core.enums import UserRole
from app.core.rls import bypass_rls, set_tenant_context
from app.core.security import hash_password
from app.locations.models import Location
from app.organizations.models import AccessAuditLog, LocationAccessGrant, OrganizationInvitation
from app.organizations.permissions import can_access_location
from app.organizations.schemas import InvitationCreateIn, MemberUpdateIn
from app.users.models import User


class OrganizationAccessError(Exception):
    pass


class InvitationInvalid(Exception):
    pass


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_invitation_token() -> str:
    """Generate the secret delivered to an invitee; isolated for deterministic tests."""
    return secrets.token_urlsafe(32)


def invitation_usable(invitation: OrganizationInvitation | None, now: datetime) -> bool:
    return bool(
        invitation is not None
        and invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > now
    )


def _audit(
    session: AsyncSession,
    actor: User | None,
    action: str,
    *,
    target: User | None = None,
    location_id: uuid.UUID | None = None,
    detail: dict[str, object] | None = None,
    tenant_id: uuid.UUID | None = None,
) -> None:
    resolved_tenant_id = tenant_id or (actor.tenant_id if actor is not None else None)
    if resolved_tenant_id is None:
        raise ValueError("tenant_id is required for a system audit event")
    session.add(
        AccessAuditLog(
            tenant_id=resolved_tenant_id,
            actor_user_id=actor.id if actor else None,
            target_user_id=target.id if target else None,
            action=action,
            location_id=location_id,
            detail_json=json.dumps(detail or {}, default=str),
        )
    )


async def create_invitation(
    session: AsyncSession, actor: User, data: InvitationCreateIn
) -> tuple[OrganizationInvitation, str]:
    if data.location_id is not None:
        location = await session.get(Location, data.location_id)
        if (
            location is None
            or location.tenant_id != actor.tenant_id
            or not await can_access_location(session, actor, location)
        ):
            raise OrganizationAccessError("Escopo não encontrado")
    elif not actor.organization_wide_access:
        raise OrganizationAccessError("Acesso restrito não pode conceder toda a organização")
    email = data.email.lower()
    if await session.scalar(select(User.id).where(User.email_index == blind_index(email))):
        raise OrganizationAccessError("E-mail já pertence a uma conta")
    now = datetime.now(UTC)
    previous = list(
        (
            await session.scalars(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.email_index == blind_index(email),
                    OrganizationInvitation.accepted_at.is_(None),
                    OrganizationInvitation.revoked_at.is_(None),
                )
            )
        ).all()
    )
    for item in previous:
        item.revoked_at = now
    token = generate_invitation_token()
    invitation = OrganizationInvitation(
        tenant_id=actor.tenant_id,
        email=email,
        email_index=blind_index(email),
        role=data.role.value,
        location_id=data.location_id,
        token_hash=_token_hash(token),
        expires_at=now + timedelta(hours=data.expires_in_hours),
        access_expires_at=data.access_expires_at,
        invited_by_user_id=actor.id,
    )
    session.add(invitation)
    _audit(
        session,
        actor,
        "invitation.created",
        location_id=data.location_id,
        detail={"role": data.role.value, "expires_at": invitation.expires_at},
    )
    await session.commit()
    await set_tenant_context(session, actor.tenant_id)
    await session.refresh(invitation)
    return invitation, token


async def accept_invitation(
    session: AsyncSession, token: str, password: str, full_name: str | None
) -> User:
    await bypass_rls(session)
    invitation = await session.scalar(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.token_hash == _token_hash(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if not invitation_usable(invitation, now):
        raise InvitationInvalid()
    assert invitation is not None
    if await session.scalar(select(User.id).where(User.email_index == invitation.email_index)):
        raise InvitationInvalid()
    user = User(
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        email_index=invitation.email_index,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=UserRole(invitation.role),
        is_active=True,
        organization_wide_access=invitation.location_id is None,
        access_expires_at=invitation.access_expires_at,
        email_verified=True,
        email_verified_at=now,
    )
    session.add(user)
    await session.flush()
    if invitation.location_id is not None:
        session.add(
            LocationAccessGrant(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                location_id=invitation.location_id,
                granted_by_user_id=invitation.invited_by_user_id,
                expires_at=invitation.access_expires_at,
            )
        )
    invitation.accepted_at = now
    invitation.accepted_by_user_id = user.id
    _audit(
        session,
        None,
        "invitation.accepted",
        target=user,
        location_id=invitation.location_id,
        tenant_id=invitation.tenant_id,
        detail={"role": invitation.role},
    )
    await session.commit()
    await set_tenant_context(session, invitation.tenant_id)
    await session.refresh(user)
    return user


async def update_member(
    session: AsyncSession, actor: User, target: User, data: MemberUpdateIn
) -> User:
    if (
        target.tenant_id != actor.tenant_id
        or target.role == UserRole.OWNER
        or target.id == actor.id
    ):
        raise OrganizationAccessError("Membro protegido")
    before = {
        "role": target.role.value,
        "organization_wide_access": target.organization_wide_access,
        "access_expires_at": target.access_expires_at,
    }
    if data.role is not None:
        target.role = data.role
    if data.organization_wide_access is not None:
        if data.organization_wide_access and not actor.organization_wide_access:
            raise OrganizationAccessError("Acesso restrito não pode conceder toda a organização")
        target.organization_wide_access = data.organization_wide_access
    if "access_expires_at" in data.model_fields_set:
        target.access_expires_at = data.access_expires_at
    if data.location_ids is not None:
        locations = list(
            (
                await session.scalars(select(Location).where(Location.id.in_(data.location_ids)))
            ).all()
        )
        locations_valid = len(locations) == len(set(data.location_ids))
        for location in locations:
            if location.tenant_id != actor.tenant_id or not await can_access_location(
                session, actor, location
            ):
                locations_valid = False
                break
        if not locations_valid:
            raise OrganizationAccessError("Escopo inválido")
        target.organization_wide_access = False
        await session.execute(
            delete(LocationAccessGrant).where(LocationAccessGrant.user_id == target.id)
        )
        for location_id in set(data.location_ids):
            session.add(
                LocationAccessGrant(
                    tenant_id=actor.tenant_id,
                    user_id=target.id,
                    location_id=location_id,
                    granted_by_user_id=actor.id,
                    expires_at=target.access_expires_at,
                )
            )
    elif data.organization_wide_access:
        await session.execute(
            delete(LocationAccessGrant).where(LocationAccessGrant.user_id == target.id)
        )
    _audit(session, actor, "member.updated", target=target, detail={"before": before})
    await session.commit()
    await set_tenant_context(session, actor.tenant_id)
    await session.refresh(target)
    return target


async def revoke_member(session: AsyncSession, actor: User, target: User) -> None:
    if (
        target.tenant_id != actor.tenant_id
        or target.role == UserRole.OWNER
        or target.id == actor.id
    ):
        raise OrganizationAccessError("Membro protegido")
    target.is_active = False
    now = datetime.now(UTC)
    grants = list(
        (
            await session.scalars(
                select(LocationAccessGrant).where(LocationAccessGrant.user_id == target.id)
            )
        ).all()
    )
    for grant in grants:
        grant.revoked_at = now
    _audit(session, actor, "member.revoked", target=target)
    await session.commit()


async def revoke_invitation(
    session: AsyncSession, actor: User, invitation: OrganizationInvitation
) -> None:
    if invitation.tenant_id != actor.tenant_id or invitation.accepted_at is not None:
        raise OrganizationAccessError("Convite não encontrado")
    invitation.revoked_at = datetime.now(UTC)
    _audit(
        session,
        actor,
        "invitation.revoked",
        location_id=invitation.location_id,
        detail={"invitation_id": str(invitation.id)},
    )
    await session.commit()
