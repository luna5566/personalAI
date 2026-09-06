from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings


class UploadTooLargeError(ValueError):
    pass


def save_bytes(content: bytes, original_filename: str | None = None) -> str:
    storage_root = _storage_root()
    suffix = Path(original_filename or "").suffix.lower()
    key = f"documents/{uuid4()}{suffix}"
    target = storage_root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return key


async def save_upload(
    upload: UploadFile,
    original_filename: str | None,
    max_size_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> tuple[str, int]:
    storage_root = _storage_root()
    suffix = Path(original_filename or "").suffix.lower()
    key = f"documents/{uuid4()}{suffix}"
    target = storage_root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    try:
        with target.open("wb") as output:
            while chunk := await upload.read(chunk_size):
                total += len(chunk)
                if total > max_size_bytes:
                    raise UploadTooLargeError(
                        f"上传文件不能超过 {max_size_bytes // (1024 * 1024)} MB"
                    )
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return key, total


def resolve_path(key: str) -> Path:
    storage_root = _storage_root()
    return _resolve_key(storage_root, key)


def read_bytes(key: str) -> bytes:
    return resolve_path(key).read_bytes()


def delete_key(key: str | None) -> None:
    if not key:
        return
    path = resolve_path(key)
    if path.exists():
        path.unlink()


def key_exists(key: str) -> bool:
    root = _configured_storage_root()
    if not root.exists():
        return False
    return _resolve_key(root, key).is_file()


def validate_key(key: str) -> None:
    _resolve_key(_configured_storage_root(), key)


def iter_keys(prefix: str | None = None) -> Iterator[str]:
    root = _configured_storage_root()
    if not root.exists():
        return
    start = _resolve_key(root, prefix or "")
    if not start.exists():
        return

    candidates = [start] if start.is_file() else start.rglob("*")
    root_resolved = root.resolve()
    for path in candidates:
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(root_resolved):
            continue
        yield path.relative_to(root).as_posix()


def list_keys(prefix: str | None = None) -> list[str]:
    return sorted(iter_keys(prefix))


def _storage_root() -> Path:
    root = _configured_storage_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _configured_storage_root() -> Path:
    root = settings.storage_root
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def _resolve_key(root: Path, key: str) -> Path:
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Invalid storage key")
    return path
