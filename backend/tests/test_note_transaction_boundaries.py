from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import DocumentSourceType
from app.schemas.document import NoteCreate
from app.services import document_service, enrichment_service


class NoteBoundarySession:
    def __init__(self, *, flush_error: Exception | None = None) -> None:
        self.connection_checked_out = True
        self.flush_error = flush_error
        self.events = []
        self.added = []
        self.added_many = []

    def rollback(self):
        self.events.append("rollback")
        self.connection_checked_out = False

    def add(self, value):
        self.events.append("add")
        self.added.append(value)

    def add_all(self, values):
        self.events.append("add_all")
        self.added_many.append(list(values))

    def flush(self):
        self.events.append("flush")
        self.connection_checked_out = True
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self):
        self.events.append("commit")
        self.connection_checked_out = False

    def refresh(self, value):
        self.events.append("refresh")
        self.connection_checked_out = True


def _install_preparation_fakes(monkeypatch, db, *, embedding_error=None) -> None:
    chunk = SimpleNamespace(
        id=uuid4(),
        document_id=None,
        user_id=None,
        chunk_index=0,
        content="正文",
    )

    def build_chunks(document):
        assert db.connection_checked_out is False
        chunk.document_id = document.id
        chunk.user_id = document.user_id
        return [chunk]

    def generate_embeddings(chunks):
        assert db.connection_checked_out is False
        if embedding_error is not None:
            raise embedding_error
        return [SimpleNamespace(chunk_id=chunk.id)]

    def generate_enrichment(document, chunks):
        assert db.connection_checked_out is False
        return enrichment_service.GeneratedEnrichment(
            summary="摘要",
            tags=["自动标签"],
        )

    monkeypatch.setattr(
        document_service.chunking_service,
        "build_document_chunks",
        build_chunks,
    )
    monkeypatch.setattr(
        document_service.embedding_service,
        "generate_chunk_embeddings",
        generate_embeddings,
    )
    monkeypatch.setattr(
        document_service.enrichment_service,
        "generate_document_enrichment",
        generate_enrichment,
    )


def test_note_provider_work_runs_without_a_database_connection(
    monkeypatch,
) -> None:
    db = NoteBoundarySession()
    _install_preparation_fakes(monkeypatch, db)
    assigned_tags = []

    def set_tags(session, user_id, document_id, tags):
        assert session.connection_checked_out is True
        assigned_tags.extend(tags)

    monkeypatch.setattr(
        document_service.tag_service,
        "set_document_tags",
        set_tags,
    )

    note = document_service.create_note(
        db,
        uuid4(),
        NoteCreate(content="正文", tags=["用户标签"]),
        source_type=DocumentSourceType.AI_GENERATED,
        metadata={
            "source_document_ids": [str(uuid4())],
            "tags": ["不能覆盖"],
        },
    )

    assert db.events[0] == "rollback"
    assert db.events[-3:] == ["flush", "commit", "refresh"]
    assert assigned_tags == ["用户标签", "自动标签"]
    assert note.tags == ["用户标签", "自动标签"]
    assert note.source_type == DocumentSourceType.AI_GENERATED.value
    assert note.metadata_["tags"] == ["用户标签"]
    assert "source_document_ids" in note.metadata_


def test_note_embedding_failure_does_not_start_persistence(
    monkeypatch,
) -> None:
    db = NoteBoundarySession()
    _install_preparation_fakes(
        monkeypatch,
        db,
        embedding_error=RuntimeError("embedding failed"),
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        document_service.create_note(
            db,
            uuid4(),
            NoteCreate(content="正文"),
        )

    assert db.events == ["rollback"]
    assert db.added == []
    assert db.added_many == []
    assert db.connection_checked_out is False


def test_note_persistence_failure_rolls_back_the_whole_note(
    monkeypatch,
) -> None:
    db = NoteBoundarySession(flush_error=RuntimeError("flush failed"))
    _install_preparation_fakes(monkeypatch, db)
    monkeypatch.setattr(
        document_service.tag_service,
        "set_document_tags",
        lambda *args: None,
    )

    with pytest.raises(RuntimeError, match="flush failed"):
        document_service.create_note(
            db,
            uuid4(),
            NoteCreate(content="正文"),
        )

    assert db.events[-1] == "rollback"
    assert "commit" not in db.events
    assert db.connection_checked_out is False
