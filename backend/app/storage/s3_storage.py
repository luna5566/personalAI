from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.storage.local_storage import UploadTooLargeError


def save_bytes(content: bytes, original_filename: str | None = None) -> str:
    key = _key(original_filename)
    _client().put_object(Bucket=_bucket(), Key=key, Body=content)
    return key


async def save_upload(
    upload: UploadFile,
    original_filename: str | None,
    max_size_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> tuple[str, int]:
    total = 0
    while chunk := await upload.read(chunk_size):
        total += len(chunk)
        if total > max_size_bytes:
            raise UploadTooLargeError(
                f"上传文件不能超过 {max_size_bytes // (1024 * 1024)} MB"
            )
    await upload.seek(0)
    key = _key(original_filename)
    extra_args = {"ContentType": upload.content_type} if upload.content_type else None

    def _upload() -> None:
        kwargs = {"ExtraArgs": extra_args} if extra_args else {}
        _client().upload_fileobj(upload.file, _bucket(), key, **kwargs)

    await asyncio.to_thread(_upload)
    return key, total


def read_bytes(key: str) -> bytes:
    response = _client().get_object(Bucket=_bucket(), Key=key)
    return response["Body"].read()


def delete_key(key: str | None) -> None:
    if key:
        _client().delete_object(Bucket=_bucket(), Key=key)


def key_exists(key: str) -> bool:
    validate_key(key)
    try:
        _client().head_object(Bucket=_bucket(), Key=key)
    except Exception as exc:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata", {})
            if isinstance(response, dict)
            else {}
        )
        code = str(error.get("Code", ""))
        status = metadata.get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise
    return True


def validate_key(key: str) -> None:
    if not key or len(key.encode("utf-8")) > 1024:
        raise ValueError("Invalid storage key")


def iter_keys(prefix: str | None = None) -> Iterator[str]:
    normalized_prefix = (prefix or "").strip("/")
    request_prefix = f"{normalized_prefix}/" if normalized_prefix else ""
    paginator = _client().get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=_bucket(),
        Prefix=request_prefix,
    ):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if isinstance(key, str) and key:
                yield key


def list_keys(prefix: str | None = None) -> list[str]:
    return sorted(set(iter_keys(prefix)))


@contextmanager
def materialize(key: str) -> Iterator[Path]:
    suffix = Path(key).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
        path = Path(temporary.name)
    try:
        _client().download_file(_bucket(), key, str(path))
        yield path
    finally:
        path.unlink(missing_ok=True)


def _key(original_filename: str | None) -> str:
    suffix = Path(original_filename or "").suffix.lower()
    prefix = settings.s3_key_prefix.strip("/")
    name = f"{uuid4()}{suffix}"
    return f"{prefix}/{name}" if prefix else name


def _bucket() -> str:
    if not settings.s3_bucket:
        raise ValueError("S3_BUCKET is required for s3 storage backend")
    return settings.s3_bucket


def _client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for s3 storage backend") from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        use_ssl=settings.s3_use_ssl,
    )
