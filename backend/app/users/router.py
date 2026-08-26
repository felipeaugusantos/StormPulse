"""User endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.apikeys import service as apikey_service
from app.apikeys.schemas import ApiKeyCreateIn, ApiKeyCreateOut, ApiKeyListOut, ApiKeyOut
from app.notifications import service as push_service
from app.notifications.schemas import (
    ExpoPushTokenDeleteIn,
    ExpoPushTokenIn,
    PushSubscriptionDeleteIn,
    PushSubscriptionIn,
)
from app.tenants.models import Tenant
from app.users import service
from app.users.models import User
from app.users.schemas import DeleteAccountIn, UserOut

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut, summary="Perfil do usuário autenticado")
async def read_me(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserOut:
    # Module flags live on Tenant, not User — fetched here rather than
    # joined eagerly in get_current_user, since this is the only endpoint
    # that needs them.
    tenant = await session.get(Tenant, current_user.tenant_id)
    return UserOut(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
        is_platform_admin=current_user.is_platform_admin,
        created_at=current_user.created_at,
        storm_module_enabled=tenant.storm_enabled if tenant is not None else True,
        agro_module_enabled=tenant.agro_enabled if tenant is not None else False,
        email_verified=current_user.email_verified,
    )


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir a própria conta e todos os dados associados (LGPD)",
)
async def delete_me(
    data: DeleteAccountIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if not data.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmação obrigatória para excluir a conta",
        )
    await service.delete_own_account(session, current_user)


@router.post(
    "/me/push-subscription",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Registrar (ou renovar) uma assinatura de notificação push do navegador",
)
async def register_push_subscription(
    data: PushSubscriptionIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await push_service.upsert_subscription(session, current_user, data)


@router.delete(
    "/me/push-subscription",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover uma assinatura de notificação push do navegador",
)
async def unregister_push_subscription(
    data: PushSubscriptionDeleteIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await push_service.delete_subscription(session, current_user, data.endpoint)


@router.post(
    "/me/push-subscription/expo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Registrar (ou renovar) o token de push Expo do app mobile",
)
async def register_expo_push_token(
    data: ExpoPushTokenIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await push_service.upsert_expo_token(session, current_user, data.expo_push_token)


@router.delete(
    "/me/push-subscription/expo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover o token de push Expo do app mobile",
)
async def unregister_expo_push_token(
    data: ExpoPushTokenDeleteIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await push_service.delete_expo_token(session, current_user, data.expo_push_token)


@router.post(
    "/me/api-keys",
    response_model=ApiKeyCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar uma chave de API para integração externa (item 1)",
)
async def create_api_key(
    data: ApiKeyCreateIn,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyCreateOut:
    key, raw_key = await apikey_service.create_api_key(session, user=current_user, name=data.name)
    return ApiKeyCreateOut(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        key=raw_key,
    )


@router.get(
    "/me/api-keys",
    response_model=ApiKeyListOut,
    summary="Listar as próprias chaves de API (nunca o valor bruto)",
)
async def list_api_keys(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyListOut:
    keys = await apikey_service.list_api_keys(session, user=current_user)
    return ApiKeyListOut(items=[ApiKeyOut.model_validate(k) for k in keys])


@router.delete(
    "/me/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revogar uma chave de API",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        await apikey_service.revoke_api_key(session, user=current_user, key_id=key_id)
    except apikey_service.ApiKeyNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chave de API não encontrada",
        ) from exc
