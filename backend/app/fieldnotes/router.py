"""Caderno de Campo endpoints (Fase 6, ADR-0090).

Location-scoped create/list (`/locations/{location_id}/field-*`) plus
standalone update-by-id (`/field-*/{id}`) — the same split already used
by `app/alert_rules/router.py`. Every create accepts an optional
client-supplied `id` (offline-generated on mobile); every update requires
`base_version` and 409s on a stale one instead of overwriting silently
(see `models.py`/`schemas.py` module docstrings).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.api.deps import get_current_user, get_db, get_request_settings
from app.core.config import Settings
from app.core.rls import set_tenant_context
from app.fieldnotes.models import FieldOccurrence, Inspection, Photo, Task
from app.fieldnotes.schemas import (
    FieldOccurrenceCreate,
    FieldOccurrenceOut,
    FieldOccurrenceUpdate,
    InspectionCreate,
    InspectionOut,
    InspectionUpdate,
    PhotoOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TimelineEntry,
)
from app.fieldnotes.storage import (
    FieldPhotoStorageError,
    object_key_for,
    presigned_get_url,
    upload_photo,
)
from app.locations import service as locations_service
from app.locations.models import Location
from app.users.models import User

router = APIRouter(tags=["fieldnotes"])

_MAX_PHOTO_BYTES = 15 * 1024 * 1024  # 15 MB — generous for an already-compressed upload.


async def _get_location_or_404(
    session: AsyncSession, user: User, location_id: uuid.UUID
) -> Location:
    location = await locations_service.get_location(session, user, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")
    return location


async def _get_occurrence_or_404(
    session: AsyncSession, user: User, occurrence_id: uuid.UUID
) -> FieldOccurrence:
    occurrence = await session.get(FieldOccurrence, occurrence_id)
    if (
        occurrence is None
        or await locations_service.get_location(session, user, occurrence.location_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ocorrência não encontrada"
        )
    return occurrence


async def _get_inspection_or_404(
    session: AsyncSession, user: User, inspection_id: uuid.UUID
) -> Inspection:
    inspection = await session.get(Inspection, inspection_id)
    if (
        inspection is None
        or await locations_service.get_location(session, user, inspection.location_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspeção não encontrada")
    return inspection


async def _get_task_or_404(session: AsyncSession, user: User, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id)
    if (
        task is None
        or await locations_service.get_location(session, user, task.location_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarefa não encontrada")
    return task


def _conflict(current_version: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Registro já atualizado por outra pessoa (versão atual: {current_version}).",
    )


# --------------------------------------------------------------------------
# Occurrences
# --------------------------------------------------------------------------


@router.post(
    "/locations/{location_id}/field-occurrences",
    response_model=FieldOccurrenceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_occurrence(
    location_id: uuid.UUID,
    data: FieldOccurrenceCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FieldOccurrence:
    location = await _get_location_or_404(session, user, location_id)
    # Idempotent replay (Fase 6, ADR-0090): the mobile app retries a
    # queued create after a network timeout with the *same* client-
    # generated id — a second insert must return the existing row, never
    # a duplicate-key error.
    if data.id is not None:
        existing = await session.get(FieldOccurrence, data.id)
        if existing is not None:
            return existing
    occurrence = FieldOccurrence(
        **({"id": data.id} if data.id is not None else {}),
        tenant_id=user.tenant_id,
        location_id=location.id,
        alert_id=data.alert_id,
        recommended_action_id=data.recommended_action_id,
        category=data.category,
        description=data.description,
        latitude=data.latitude,
        longitude=data.longitude,
        reported_by=user.id,
        reported_at=data.reported_at or datetime.now(UTC),
    )
    session.add(occurrence)
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(occurrence)
    return occurrence


@router.get("/locations/{location_id}/field-occurrences", response_model=list[FieldOccurrenceOut])
async def list_occurrences(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FieldOccurrence]:
    location = await _get_location_or_404(session, user, location_id)
    stmt = (
        select(FieldOccurrence)
        .where(FieldOccurrence.location_id == location.id)
        .order_by(FieldOccurrence.reported_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/field-occurrences/{occurrence_id}", response_model=FieldOccurrenceOut)
async def update_occurrence(
    occurrence_id: uuid.UUID,
    data: FieldOccurrenceUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FieldOccurrence:
    occurrence = await _get_occurrence_or_404(session, user, occurrence_id)
    if occurrence.version != data.base_version:
        raise _conflict(occurrence.version)
    if data.status is not None:
        occurrence.status = data.status
    if data.description is not None:
        occurrence.description = data.description
    occurrence.version += 1
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(occurrence)
    return occurrence


# --------------------------------------------------------------------------
# Inspections + photos
# --------------------------------------------------------------------------


@router.post(
    "/locations/{location_id}/field-inspections",
    response_model=InspectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_inspection(
    location_id: uuid.UUID,
    data: InspectionCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Inspection:
    location = await _get_location_or_404(session, user, location_id)
    if data.id is not None:
        existing = await session.get(Inspection, data.id)
        if existing is not None:
            return existing
    if data.occurrence_id is not None:
        await _get_occurrence_or_404(session, user, data.occurrence_id)
    inspection = Inspection(
        **({"id": data.id} if data.id is not None else {}),
        tenant_id=user.tenant_id,
        location_id=location.id,
        occurrence_id=data.occurrence_id,
        notes=data.notes,
        latitude=data.latitude,
        longitude=data.longitude,
        inspected_by=user.id,
        inspected_at=data.inspected_at or datetime.now(UTC),
    )
    session.add(inspection)
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(inspection)
    return inspection


@router.get("/locations/{location_id}/field-inspections", response_model=list[InspectionOut])
async def list_inspections(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Inspection]:
    location = await _get_location_or_404(session, user, location_id)
    stmt = (
        select(Inspection)
        .where(Inspection.location_id == location.id)
        .order_by(Inspection.inspected_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/field-inspections/{inspection_id}", response_model=InspectionOut)
async def update_inspection(
    inspection_id: uuid.UUID,
    data: InspectionUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Inspection:
    inspection = await _get_inspection_or_404(session, user, inspection_id)
    if inspection.version != data.base_version:
        raise _conflict(inspection.version)
    if data.notes is not None:
        inspection.notes = data.notes
    inspection.version += 1
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(inspection)
    return inspection


@router.post(
    "/field-inspections/{inspection_id}/photos",
    response_model=PhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_inspection_photo(
    inspection_id: uuid.UUID,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> PhotoOut:
    """Expects an already-compressed image (the mobile app compresses
    client-side before queueing the upload — see ADR-0090); this endpoint
    only rejects an unreasonably large body, it never compresses itself."""
    inspection = await _get_inspection_or_404(session, user, inspection_id)
    data = await file.read()
    if len(data) > _MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Foto excede o tamanho máximo permitido (15 MB) — comprima antes de enviar.",
        )
    object_key = object_key_for(inspection.id, file.filename or "photo.jpg")
    try:
        checksum = upload_photo(
            settings,
            object_key=object_key,
            data=data,
            content_type=file.content_type or "application/octet-stream",
        )
    except FieldPhotoStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Armazenamento de fotos indisponível no momento — tente novamente.",
        ) from exc

    photo = Photo(
        tenant_id=user.tenant_id,
        inspection_id=inspection.id,
        object_key=object_key,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        checksum_sha256=checksum,
        uploaded_by=user.id,
        uploaded_at=datetime.now(UTC),
    )
    session.add(photo)
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(photo)
    return PhotoOut(
        id=photo.id,
        inspection_id=photo.inspection_id,
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        uploaded_by=photo.uploaded_by,
        uploaded_at=photo.uploaded_at,
        url=presigned_get_url(settings, object_key=photo.object_key),
    )


@router.get("/field-inspections/{inspection_id}/photos", response_model=list[PhotoOut])
async def list_inspection_photos(
    inspection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_request_settings),
) -> list[PhotoOut]:
    inspection = await _get_inspection_or_404(session, user, inspection_id)
    rows = list(
        (
            await session.execute(
                select(Photo)
                .where(Photo.inspection_id == inspection.id)
                .order_by(Photo.uploaded_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        PhotoOut(
            id=p.id,
            inspection_id=p.inspection_id,
            content_type=p.content_type,
            size_bytes=p.size_bytes,
            uploaded_by=p.uploaded_by,
            uploaded_at=p.uploaded_at,
            url=presigned_get_url(settings, object_key=p.object_key),
        )
        for p in rows
    ]


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


@router.post(
    "/locations/{location_id}/field-tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    location_id: uuid.UUID,
    data: TaskCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    location = await _get_location_or_404(session, user, location_id)
    if data.id is not None:
        existing = await session.get(Task, data.id)
        if existing is not None:
            return existing
    if data.occurrence_id is not None:
        await _get_occurrence_or_404(session, user, data.occurrence_id)
    task = Task(
        **({"id": data.id} if data.id is not None else {}),
        tenant_id=user.tenant_id,
        location_id=location.id,
        occurrence_id=data.occurrence_id,
        alert_id=data.alert_id,
        recommended_action_id=data.recommended_action_id,
        title=data.title,
        description=data.description,
        assigned_to=data.assigned_to,
        due_at=data.due_at,
    )
    session.add(task)
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(task)
    return task


@router.get("/locations/{location_id}/field-tasks", response_model=list[TaskOut])
async def list_tasks(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Task]:
    location = await _get_location_or_404(session, user, location_id)
    stmt = (
        select(Task).where(Task.location_id == location.id).order_by(Task.due_at.asc().nulls_last())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.patch("/field-tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    task = await _get_task_or_404(session, user, task_id)
    if task.version != data.base_version:
        raise _conflict(task.version)
    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if data.assigned_to is not None:
        task.assigned_to = data.assigned_to
    if data.due_at is not None:
        task.due_at = data.due_at
    if data.status is not None:
        task.status = data.status
        if data.status.value == "done":
            task.completed_by = user.id
            task.completed_at = datetime.now(UTC)
    task.version += 1
    await session.commit()
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(task)
    return task


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


@router.get("/locations/{location_id}/field-timeline", response_model=list[TimelineEntry])
async def get_field_timeline(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TimelineEntry]:
    """Merges occurrences/inspections/tasks/alerts for this talhão into one
    chronological read — never a new source of truth, each entry just
    points back (`ref_id`) at the record its own endpoint already serves."""
    location = await _get_location_or_404(session, user, location_id)

    occurrences = (
        (
            await session.execute(
                select(FieldOccurrence).where(FieldOccurrence.location_id == location.id)
            )
        )
        .scalars()
        .all()
    )
    inspections = (
        (await session.execute(select(Inspection).where(Inspection.location_id == location.id)))
        .scalars()
        .all()
    )
    tasks = (
        (await session.execute(select(Task).where(Task.location_id == location.id))).scalars().all()
    )
    alerts = (
        (
            await session.execute(
                select(Alert)
                .where(Alert.location_id == location.id)
                .order_by(Alert.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    entries = (
        [
            TimelineEntry(
                kind="occurrence",
                ref_id=o.id,
                occurred_at=o.reported_at,
                title=o.category,
                summary=o.description,
            )
            for o in occurrences
        ]
        + [
            TimelineEntry(
                kind="inspection",
                ref_id=i.id,
                occurred_at=i.inspected_at,
                title="Inspeção",
                summary=i.notes,
            )
            for i in inspections
        ]
        + [
            TimelineEntry(
                kind="task",
                ref_id=t.id,
                occurred_at=t.created_at,
                title=t.title,
                summary=t.status.value,
            )
            for t in tasks
        ]
        + [
            TimelineEntry(
                kind="alert",
                ref_id=a.id,
                occurred_at=a.created_at,
                title=a.title,
                summary=a.message,
            )
            for a in alerts
        ]
    )
    entries.sort(key=lambda e: e.occurred_at, reverse=True)
    return entries
