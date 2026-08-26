"""Cross-tenant platform-admin endpoints (FASE 28, ADR-0048/ADR-0049).

Everything here is gated by `require_platform_admin` — distinct from, and
strictly narrower-audience than, the tenant-scoped `require_admin`. A
tenant's own ADMIN still only ever sees their own tenant's data through the
normal routers; only a platform operator reaches anything in this module.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import service
from app.admin.schemas import (
    AdminAuditLogListOut,
    AdminStatsOut,
    AdminTenantListOut,
    AdminUserListOut,
    AdminUserOut,
    AdminUserUpdateIn,
    AlertVerificationIn,
    AlertVerificationOut,
    PipelineHealthOut,
    PipelineTriggerIn,
    PipelineTriggerOut,
    ValidationMetricsOut,
)
from app.api.deps import get_db, get_request_settings, require_platform_admin
from app.core.config import Settings
from app.core.tasks import PIPELINE_TASK_NAMES, trigger_pipeline
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


@router.put(
    "/users/{user_id}",
    response_model=AdminUserOut,
    summary="Ativar/desativar conta ou trocar o role de um usuário (operador da plataforma)",
)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdateIn,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_platform_admin),
) -> AdminUserOut:
    if not data.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmação obrigatória para alterar um usuário",
        )
    try:
        return await service.update_user(session, actor=actor, target_user_id=user_id, data=data)
    except service.UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado"
        ) from exc
    except service.NoChangesRequested as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe is_active e/ou role para alterar",
        ) from exc
    except service.UnsupportedRole as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{exc.role.value}' ainda não é suportado por este painel",
        ) from exc
    except service.SelfLockoutAttempt as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode desativar sua própria conta",
        ) from exc


@router.get(
    "/audit-log",
    response_model=AdminAuditLogListOut,
    summary="Ver o histórico de ações administrativas (operador da plataforma)",
)
async def list_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> AdminAuditLogListOut:
    items, total = await service.list_audit_log(session, limit=limit, offset=offset)
    return AdminAuditLogListOut(items=items, total=total)


@router.get(
    "/stats",
    response_model=AdminStatsOut,
    summary="Métricas agregadas da base (operador da plataforma)",
)
async def get_stats(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> AdminStatsOut:
    return await service.get_stats(session)


@router.get(
    "/pipeline-health",
    response_model=list[PipelineHealthOut],
    summary="Frescor dos dados de cada pipeline de fundo (operador da plataforma)",
)
async def get_pipeline_health(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> list[PipelineHealthOut]:
    return await service.get_pipeline_health(session)


@router.post(
    "/pipeline-health/trigger",
    response_model=PipelineTriggerOut,
    summary="Rodar um pipeline agora, fora do agendamento (operador da plataforma)",
)
async def trigger_pipeline_now(
    data: PipelineTriggerIn,
    settings: Settings = Depends(get_request_settings),
    _: User = Depends(require_platform_admin),
) -> PipelineTriggerOut:
    if data.name not in PIPELINE_TASK_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline desconhecido: {data.name!r}",
        )
    # Fire-and-forget — enqueues onto the same Redis broker `worker`
    # already consumes from; doesn't wait for the cycle to actually finish
    # (the satellite one alone takes ~15s), same as beat's own dispatch.
    trigger_pipeline(data.name, settings)
    return PipelineTriggerOut(queued=True, name=data.name)


@router.put(
    "/alerts/{alert_id}/verification",
    response_model=AlertVerificationOut,
    summary="Registrar o resultado real de um alerta já emitido (ADR-0036/0058)",
)
async def upsert_alert_verification(
    alert_id: uuid.UUID,
    data: AlertVerificationIn,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_platform_admin),
) -> AlertVerificationOut:
    try:
        return await service.upsert_alert_verification(
            session, actor=actor, alert_id=alert_id, data=data
        )
    except service.AlertNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta não encontrado",
        ) from exc


@router.get(
    "/validation/metrics",
    response_model=ValidationMetricsOut,
    summary="Métricas reais de acerto dos alertas, via verificações registradas (ADR-0036/0058)",
)
async def get_validation_metrics(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_platform_admin),
) -> ValidationMetricsOut:
    return await service.get_validation_metrics(session)
