from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings
from app.storage import local_storage, s3_storage

UploadTooLargeError = local_storage.UploadTooLargeError


class UnsupportedStorageBackendError(RuntimeError):
    pass


class StorageBackendChangedError(RuntimeError):
    pass


def save_bytes(content: bytes, original_filename: str | None = None) -> str:
    if settings.storage_backend == "local":
        return local_storage.save_bytes(content, original_filename)
    if settings.storage_backend == "s3":
        return s3_storage.save_bytes(content, original_filename)
    raise _unsupported()


async def save_upload(
    upload,
    original_filename: str | None,
    max_size_bytes: int,
) -> tuple[str, int]:
    if settings.storage_backend == "local":
        return await local_storage.save_upload(
            upload,
            original_filename=original_filename,
            max_size_bytes=max_size_bytes,
        )
    if settings.storage_backend == "s3":
        return await s3_storage.save_upload(
            upload,
            original_filename=original_filename,
            max_size_bytes=max_size_bytes,
        )
    raise _unsupported()


def resolve_path(key: str) -> Path:
    if settings.storage_backend == "local":
        return local_storage.resolve_path(key)
    raise UnsupportedStorageBackendError("resolve_path is only available for local storage")


def read_bytes(key: str) -> bytes:
    if settings.storage_backend == "local":
        return local_storage.read_bytes(key)
    if settings.storage_backend == "s3":
        return s3_storage.read_bytes(key)
    raise _unsupported()


def delete_key(key: str | None) -> None:
    if settings.storage_backend == "local":
        local_storage.delete_key(key)
        return
    if settings.storage_backend == "s3":
        s3_storage.delete_key(key)
        return
    raise _unsupported()


def key_exists(key: str) -> bool:
    if settings.storage_backend == "local":
        return local_storage.key_exists(key)
    if settings.storage_backend == "s3":
        return s3_storage.key_exists(key)
    raise _unsupported()


def validate_key(key: str) -> None:
    if settings.storage_backend == "local":
        local_storage.validate_key(key)
        return
    if settings.storage_backend == "s3":
        s3_storage.validate_key(key)
        return
    raise _unsupported()


def list_keys(prefix: str | None = None) -> list[str]:
    if settings.storage_backend == "local":
        return local_storage.list_keys(prefix)
    if settings.storage_backend == "s3":
        return s3_storage.list_keys(prefix)
    raise _unsupported()


def iter_keys(prefix: str | None = None) -> Iterator[str]:
    if settings.storage_backend == "local":
        yield from local_storage.iter_keys(prefix)
        return
    if settings.storage_backend == "s3":
        yield from s3_storage.iter_keys(prefix)
        return
    raise _unsupported()


def managed_key_prefix() -> str:
    if settings.storage_backend == "local":
        return "documents"
    if settings.storage_backend == "s3":
        return settings.s3_key_prefix.strip("/")
    raise _unsupported()


def current_storage_scope() -> str:
    if settings.storage_backend == "local":
        root = settings.storage_root
        if not root.is_absolute():
            root = Path.cwd() / root
        scope = {"root": str(root.resolve())}
    elif settings.storage_backend == "s3":
        scope = {
            "bucket": settings.s3_bucket or "",
            "endpoint_url": settings.s3_endpoint_url or "",
            "region": settings.s3_region or "",
            "use_ssl": settings.s3_use_ssl,
        }
    else:
        raise _unsupported()
    return json.dumps(scope, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def delete_key_for_backend(
    key: str,
    expected_backend: str,
    expected_scope: str,
) -> None:
    require_current_storage(expected_backend, expected_scope)
    delete_key(key)


def require_current_storage(
    expected_backend: str,
    expected_scope: str,
) -> None:
    if (
        settings.storage_backend != expected_backend
        or current_storage_scope() != expected_scope
    ):
        raise StorageBackendChangedError(
            "资料存储配置与上传时不一致，请恢复原存储配置后重试"
        )


@contextmanager
def materialize(key: str) -> Iterator[Path]:
    if settings.storage_backend == "local":
        yield local_storage.resolve_path(key)
        return
    if settings.storage_backend == "s3":
        with s3_storage.materialize(key) as path:
            yield path
        return
    raise _unsupported()


@contextmanager
def materialize_for_backend(
    key: str,
    expected_backend: str,
    expected_scope: str,
) -> Iterator[Path]:
    require_current_storage(expected_backend, expected_scope)
    with materialize(key) as path:
        yield path


def _unsupported() -> UnsupportedStorageBackendError:
    return UnsupportedStorageBackendError(f"Unsupported storage backend: {settings.storage_backend}")
