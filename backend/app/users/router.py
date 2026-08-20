"""User endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.notifications import service as push_service
from app.notifications.schemas import PushSubscriptionDeleteIn, PushSubscriptionIn
from app.users import service
from app.users.models import User
from app.users.schemas import DeleteAccountIn, UserOut

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut, summary="Perfil do usuário autenticado")
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


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
