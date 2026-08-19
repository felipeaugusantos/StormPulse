"""User endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.users.models import User
from app.users.schemas import UserOut

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut, summary="Perfil do usuário autenticado")
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
