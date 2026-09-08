"""Private object storage for field photos (MinIO/S3-compatible, Fase 6,
ADR-0090).

`boto3` is already a project dependency (SES email, ``workers/email.py``)
— reused here as a plain S3 client pointed at MinIO's endpoint rather than
adding a separate MinIO SDK. The bucket is never public: every read goes
through a short-lived presigned URL, never a direct/public object URL.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings

logger = logging.getLogger(__name__)

# `ClientError` only covers an AWS/S3-*service*-level error response (e.g.
# "no such bucket"); a connection failure (MinIO unreachable, DNS lookup
# failed) raises `BotoCoreError` instead — a *different* branch of
# botocore's exception hierarchy that a bare `except ClientError` never
# catches. Both are treated the same way here: an unreachable/misconfigured
# store, never a silent "no photo".
_STORAGE_ERRORS = (ClientError, BotoCoreError)


class FieldPhotoStorageError(RuntimeError):
    """The object store is unreachable or misconfigured — never silently
    treated as "no photo", the caller must surface this as a failure."""


def _client(settings: Settings) -> Any:  # boto3 client has no public stub type
    endpoint = settings.fieldnotes_storage_endpoint
    scheme = "https" if settings.fieldnotes_storage_secure else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=settings.fieldnotes_storage_access_key,
        aws_secret_access_key=settings.fieldnotes_storage_secret_key.get_secret_value(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket(settings: Settings) -> None:
    """Idempotent — called once at startup (see `app/main.py`). Creating
    the bucket here (instead of requiring a manual step) matches the
    project's "provider ready out of the box in dev" convention."""
    client = _client(settings)
    bucket = settings.fieldnotes_storage_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except _STORAGE_ERRORS:
        try:
            client.create_bucket(Bucket=bucket)
        except _STORAGE_ERRORS as exc:
            raise FieldPhotoStorageError(f"could not create bucket {bucket!r}: {exc}") from exc


def object_key_for(inspection_id: uuid.UUID, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"inspections/{inspection_id}/{uuid.uuid4()}.{ext}"


def upload_photo(settings: Settings, *, object_key: str, data: bytes, content_type: str) -> str:
    """Uploads the (already client-compressed) photo bytes and returns
    their SHA-256 checksum — used both for integrity and as a cheap
    duplicate-upload signal (never a second source of the file's actual
    content, only a fingerprint of it)."""
    client = _client(settings)
    try:
        client.put_object(
            Bucket=settings.fieldnotes_storage_bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )
    except _STORAGE_ERRORS as exc:
        raise FieldPhotoStorageError(f"upload failed for {object_key!r}: {exc}") from exc
    return hashlib.sha256(data).hexdigest()


def presigned_get_url(settings: Settings, *, object_key: str) -> str:
    client = _client(settings)
    try:
        url: str = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.fieldnotes_storage_bucket, "Key": object_key},
            ExpiresIn=settings.fieldnotes_storage_presigned_url_expiry_seconds,
        )
        return url
    except _STORAGE_ERRORS as exc:
        raise FieldPhotoStorageError(f"could not sign a URL for {object_key!r}: {exc}") from exc
