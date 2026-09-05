from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_request_settings
from app.core.config import Settings
from app.core.tasks import send_transactional_email
from app.organizations import service
from app.organizations.models import AccessAuditLog, OrganizationInvitation
from app.organizations.permissions import can_manage_members
from app.organizations.schemas import (
    AuditOut,
    InvitationAcceptIn,
    InvitationCreateIn,
    InvitationOut,
    MemberOut,
    MemberUpdateIn,
    OrganizationOut,
)
from app.tenants.models import Tenant
from app.users.models import User

router = APIRouter(tags=["organizations"])


def _manager(user: User) -> None:
    if not can_manage_members(user):
        raise HTTPException(
            status_code=403, detail="Somente proprietário ou administrador gerencia membros"
        )


@router.get("/current", response_model=OrganizationOut)
async def current(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Tenant:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Organização não encontrada")
    return tenant


@router.get("/current/members", response_model=list[MemberOut])
async def members(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[User]:
    _manager(user)
    return list(
        (
            await session.scalars(
                select(User).where(User.tenant_id == user.tenant_id).order_by(User.created_at)
            )
        ).all()
    )


@router.post("/current/invitations", response_model=InvitationOut, status_code=201)
async def invite(
    data: InvitationCreateIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> OrganizationInvitation:
    _manager(user)
    try:
        invitation, token = await service.create_invitation(session, user, data)
    except service.OrganizationAccessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    link = f"{settings.frontend_base_url}/aceitar-convite?token={token}"
    send_transactional_email("organization_invitation", invitation.email, link, settings)
    return invitation


@router.get("/current/invitations", response_model=list[InvitationOut])
async def invitations(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[OrganizationInvitation]:
    _manager(user)
    return list(
        (
            await session.scalars(
                select(OrganizationInvitation)
                .where(OrganizationInvitation.tenant_id == user.tenant_id)
                .order_by(OrganizationInvitation.created_at.desc())
            )
        ).all()
    )


@router.delete("/current/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _manager(user)
    invitation = await session.get(OrganizationInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    try:
        await service.revoke_invitation(session, user, invitation)
    except service.OrganizationAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/invitations/accept", response_model=MemberOut, status_code=201)
async def accept(data: InvitationAcceptIn, session: AsyncSession = Depends(get_db)) -> User:
    try:
        return await service.accept_invitation(session, data.token, data.password, data.full_name)
    except service.InvitationInvalid as exc:
        raise HTTPException(
            status_code=410, detail="Convite inválido, expirado ou já utilizado"
        ) from exc


@router.patch("/current/members/{member_id}", response_model=MemberOut)
async def update_member(
    member_id: uuid.UUID,
    data: MemberUpdateIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    _manager(user)
    target = await session.get(User, member_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    try:
        return await service.update_member(session, user, target, data)
    except service.OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/current/members/{member_id}", status_code=204)
async def revoke_member(
    member_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _manager(user)
    target = await session.get(User, member_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    try:
        await service.revoke_member(session, user, target)
    except service.OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/current/access-audit", response_model=list[AuditOut])
async def audit(
    session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AccessAuditLog]:
    _manager(user)
    return list(
        (
            await session.scalars(
                select(AccessAuditLog)
                .where(AccessAuditLog.tenant_id == user.tenant_id)
                .order_by(AccessAuditLog.created_at.desc())
                .limit(200)
            )
        ).all()
    )
