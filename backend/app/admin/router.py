"""Cross-tenant platform-admin endpoints (FASE 28, ADR-0048).

Everything here is gated by `require_platform_admin` — distinct from, and
strictly narrower-audience than, the tenant-scoped `require_admin`. A
tenant's own ADMIN still only ever sees their own tenant's data through the
normal routers; only a platform operator reaches anything in this module.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import service
from app.admin.schemas import AdminTenantListOut, AdminUserListOut
from app.api.deps import get_db, require_platform_admin
from app.users.models import User

router = APIRouter(tags=["admin"])


@router.get(
    "/users",
    response_model=AdminUserListOut,
    summary="Listar usuários de todos os tenants (operador da plataforma)",
)
async def list_users(
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> AdminUserListOut:
    items, total = await service.list_users(session, search=search, limit=limit, offset=offset)
    return AdminUserListOut(items=items, total=total)


@router.get(
    "/tenants",
    response_model=AdminTenantListOut,
    summary="Listar tenants (operador da plataforma)",
)
async def list_tenants(
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> AdminTenantListOut:
    items, total = await service.list_tenants(session, search=search, limit=limit, offset=offset)
    return AdminTenantListOut(items=items, total=total)
