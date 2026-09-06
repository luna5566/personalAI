import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.config import settings
from app.storage import storage_service


def test_upload_is_streamed_to_storage(tmp_path: Path) -> None:
    previous_root = settings.storage_root
    settings.storage_root = tmp_path
    upload = UploadFile(filename="note.txt", file=BytesIO(b"hello"))
    try:
        key, size = asyncio.run(
            storage_service.save_upload(upload, "note.txt", max_size_bytes=10)
        )
        assert size == 5
        assert storage_service.read_bytes(key) == b"hello"
    finally:
        settings.storage_root = previous_root


def test_oversized_upload_is_removed(tmp_path: Path) -> None:
    previous_root = settings.storage_root
    settings.storage_root = tmp_path
    upload = UploadFile(filename="large.txt", file=BytesIO(b"too large"))
    try:
        with pytest.raises(storage_service.UploadTooLargeError):
            asyncio.run(
                storage_service.save_upload(upload, "large.txt", max_size_bytes=4)
            )
        assert list(tmp_path.rglob("*.txt")) == []
    finally:
        settings.storage_root = previous_root
