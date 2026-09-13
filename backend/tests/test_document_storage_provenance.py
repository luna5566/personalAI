from pathlib import Path
from uuid import UUID

import pytest

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.models.document import Document, DocumentSourceType
from app.services import document_service
from app.services.parsing_service import parse_document
from app.storage import storage_service


def test_document_file_storage_provenance_is_constrained() -> None:
    documents = Base.metadata.tables["documents"]
    constraint = next(
        item
        for item in documents.constraints
        if item.name == "ck_documents_file_storage_provenance"
    )

    sql = str(constraint.sqltext)
    assert "file_path IS NULL" in sql
    assert "storage_backend IS NULL" in sql
    assert "storage_scope IS NULL" in sql
    assert "file_path IS NOT NULL" in sql
    assert "storage_backend IS NOT NULL" in sql
    assert "storage_scope IS NOT NULL" in sql


def test_create_file_document_snapshots_current_storage_provenance(
    monkeypatch,
) -> None:
    added = []

    class Session:
        def add(self, value):
            added.append(value)

        def flush(self):
            pass

        def commit(self):
            pass

        def refresh(self, value):
            pass

    monkeypatch.setattr(
        document_service.settings,
        "storage_backend",
        "s3",
    )
    monkeypatch.setattr(
        document_service.storage_service,
        "current_storage_scope",
        lambda: '{"bucket":"uploads"}',
    )
    monkeypatch.setattr(
        document_service.tag_service,
        "set_document_tags",
        lambda db, user_id, document_id, tags: None,
    )

    document = document_service.create_file_document(
        Session(),
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        title="example",
        source_type=DocumentSourceType.PDF,
        file_path="documents/example.pdf",
        original_filename="example.pdf",
        file_size=123,
        mime_type="application/pdf",
    )

    assert added == [document]
    assert document.storage_backend == "s3"
    assert document.storage_scope == '{"bucket":"uploads"}'


def test_file_parser_rejects_current_storage_with_the_same_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original_root = tmp_path / "original"
    changed_root = tmp_path / "changed"
    key = "documents/shared.txt"
    (original_root / key).parent.mkdir(parents=True)
    (changed_root / key).parent.mkdir(parents=True)
    (original_root / key).write_text("original content", encoding="utf-8")
    (changed_root / key).write_text("different content", encoding="utf-8")
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_root", original_root)
    original_scope = storage_service.current_storage_scope()
    document = Document(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        title="shared",
        source_type=DocumentSourceType.TXT.value,
        file_path=key,
        storage_backend="local",
        storage_scope=original_scope,
    )

    monkeypatch.setattr(settings, "storage_root", changed_root)

    with pytest.raises(
        storage_service.StorageBackendChangedError,
        match="资料存储配置与上传时不一致",
    ):
        parse_document(document)


def test_file_parser_reads_when_storage_provenance_matches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    key = "documents/example.txt"
    target = tmp_path / key
    target.parent.mkdir(parents=True)
    target.write_text("expected content", encoding="utf-8")
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    document = Document(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        title="example",
        source_type=DocumentSourceType.TXT.value,
        file_path=key,
        storage_backend="local",
        storage_scope=storage_service.current_storage_scope(),
    )

    parsed = parse_document(document)

    assert parsed.raw_text == "expected content"
