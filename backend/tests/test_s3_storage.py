import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.config import settings
from app.storage import s3_storage


class FakeBody:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class FakeS3Error(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakePaginator:
    def __init__(self, client) -> None:
        self.client = client

    def paginate(self, Bucket, Prefix):
        keys = sorted(
            key
            for bucket, key in self.client.objects
            if bucket == Bucket and key.startswith(Prefix)
        )
        midpoint = max(len(keys) // 2, 1)
        for page_keys in (keys[:midpoint], keys[midpoint:]):
            if page_keys:
                yield {"Contents": [{"Key": key} for key in page_keys]}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body) -> None:
        self.objects[(Bucket, Key)] = Body

    def upload_fileobj(self, file, bucket, key, **kwargs) -> None:
        self.objects[(bucket, key)] = file.read()

    def get_object(self, Bucket, Key) -> dict:
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key) -> None:
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket, Key) -> dict:
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return FakePaginator(self)

    def download_file(self, bucket, key, filename) -> None:
        Path(filename).write_bytes(self.objects[(bucket, key)])


def test_s3_storage_round_trip_and_materialize(monkeypatch) -> None:
    client = FakeS3Client()
    previous_bucket = settings.s3_bucket
    settings.s3_bucket = "knowledge"
    monkeypatch.setattr(s3_storage, "_client", lambda: client)
    try:
        key = s3_storage.save_bytes(b"hello", "note.txt")
        assert s3_storage.read_bytes(key) == b"hello"
        with s3_storage.materialize(key) as path:
            assert path.read_bytes() == b"hello"
            temporary_path = path
        assert not temporary_path.exists()

        s3_storage.delete_key(key)
        assert client.objects == {}
    finally:
        settings.s3_bucket = previous_bucket


def test_s3_streaming_upload(monkeypatch) -> None:
    client = FakeS3Client()
    previous_bucket = settings.s3_bucket
    settings.s3_bucket = "knowledge"
    monkeypatch.setattr(s3_storage, "_client", lambda: client)
    upload = UploadFile(filename="voice.wav", file=BytesIO(b"audio"))
    try:
        key, size = asyncio.run(s3_storage.save_upload(upload, "voice.wav", 10))
        assert size == 5
        assert client.objects[("knowledge", key)] == b"audio"
    finally:
        settings.s3_bucket = previous_bucket


def test_s3_inventory_is_paginated_and_prefix_scoped(monkeypatch) -> None:
    client = FakeS3Client()
    client.objects = {
        ("knowledge", "documents/a.txt"): b"a",
        ("knowledge", "documents/b.txt"): b"b",
        ("knowledge", "other/c.txt"): b"c",
        ("another", "documents/d.txt"): b"d",
    }
    previous_bucket = settings.s3_bucket
    settings.s3_bucket = "knowledge"
    monkeypatch.setattr(s3_storage, "_client", lambda: client)
    try:
        assert list(s3_storage.iter_keys("/documents/")) == [
            "documents/a.txt",
            "documents/b.txt",
        ]
        assert s3_storage.list_keys("/documents/") == [
            "documents/a.txt",
            "documents/b.txt",
        ]
        assert s3_storage.key_exists("documents/a.txt") is True
        assert s3_storage.key_exists("documents/missing.txt") is False
        with pytest.raises(ValueError, match="Invalid storage key"):
            s3_storage.validate_key("x" * 1025)
    finally:
        settings.s3_bucket = previous_bucket
