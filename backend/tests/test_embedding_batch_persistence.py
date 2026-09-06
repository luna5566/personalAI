import tempfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import DocumentStatus
from app.services import embedding_service


def _chunks(count: int) -> list[SimpleNamespace]:
    document_id = uuid4()
    user_id = uuid4()
    return [
        SimpleNamespace(
            id=uuid4(),
            document_id=document_id,
            user_id=user_id,
            chunk_index=index,
            content=f"chunk-{index}",
        )
        for index in range(count)
    ]


class BatchSession:
    def __init__(
        self,
        *,
        chunks=None,
        chunk_batches=None,
        fail_flush_at=None,
    ) -> None:
        self.loaded_chunk_batches = list(
            chunk_batches
            if chunk_batches is not None
            else ([chunks, []] if chunks is not None else [])
        )
        self.fail_flush_at = fail_flush_at
        self.timeline = []
        self.batch_sizes = []
        self.flush_count = 0
        self.expunge_count = 0
        self.select_statements = []

    def rollback(self):
        self.timeline.append("db:rollback")

    def execute(self, statement):
        if statement.is_select:
            self.timeline.append("db:load-chunks")
            self.select_statements.append(statement)
            return self.loaded_chunk_batches.pop(0)
        self.timeline.append("db:delete-old")

    def add_all(self, values):
        values = list(values)
        self.batch_sizes.append(len(values))
        self.timeline.append(f"db:add:{len(values)}")

    def flush(self):
        self.flush_count += 1
        self.timeline.append(f"db:flush:{self.flush_count}")
        if self.flush_count == self.fail_flush_at:
            raise RuntimeError("database flush failed")

    def expunge(self, value):
        self.expunge_count += 1
        self.timeline.append("db:expunge-one")


class BatchProvider:
    model = "test"
    index_id = "test:3"
    dimensions = 3

    def __init__(self, session: BatchSession, *, fail_at=None) -> None:
        self.session = session
        self.fail_at = fail_at
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        self.session.timeline.append(f"provider:{len(texts)}")
        if len(self.calls) == self.fail_at:
            raise RuntimeError("provider failed")
        return [
            [float(len(self.calls)), float(index), 0.5]
            for index, _ in enumerate(texts)
        ]


def test_file_embeddings_spool_all_provider_batches_before_database_work() -> None:
    chunks = _chunks(5)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        user_id=chunks[0].user_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession()
    provider = BatchProvider(db)

    persisted = embedding_service.embed_document_chunks(
        db,
        document,
        chunks=chunks,
        provider=provider,
        batch_size=2,
    )

    assert persisted == 5
    assert [len(call) for call in provider.calls] == [2, 2, 1]
    assert db.timeline[:3] == ["provider:2", "provider:2", "provider:1"]
    assert db.timeline[3] == "db:delete-old"
    assert db.batch_sizes == [2, 2, 1]
    assert db.flush_count == 3
    assert db.expunge_count == 5
    assert document.status == DocumentStatus.INDEXED.value


def test_provider_failure_leaves_database_and_document_untouched() -> None:
    chunks = _chunks(3)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession()
    provider = BatchProvider(db, fail_at=2)

    with pytest.raises(RuntimeError, match="provider failed"):
        embedding_service.embed_document_chunks(
            db,
            document,
            chunks=chunks,
            provider=provider,
            batch_size=2,
        )

    assert db.timeline == ["provider:2", "provider:1"]
    assert db.batch_sizes == []
    assert db.flush_count == 0
    assert document.status == DocumentStatus.CHUNKING.value


@pytest.mark.parametrize("mode", ["count", "dimensions"])
def test_invalid_provider_vectors_fail_before_old_embeddings_are_deleted(mode) -> None:
    chunks = _chunks(2)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession()
    provider = BatchProvider(db)
    if mode == "count":
        provider.embed_texts = lambda texts: [[0.0, 0.0, 0.0]]
        expected = "different number"
    else:
        provider.embed_texts = lambda texts: [[0.0, 0.0] for _ in texts]
        expected = "unexpected dimensions"

    with pytest.raises(ValueError, match=expected):
        embedding_service.embed_document_chunks(
            db,
            document,
            chunks=chunks,
            provider=provider,
            batch_size=2,
        )

    assert db.timeline == []
    assert document.status == DocumentStatus.CHUNKING.value


def test_database_failure_occurs_after_provider_phase_and_keeps_transaction_open() -> None:
    chunks = _chunks(4)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession(fail_flush_at=2)
    provider = BatchProvider(db)

    with pytest.raises(RuntimeError, match="database flush failed"):
        embedding_service.embed_document_chunks(
            db,
            document,
            chunks=chunks,
            provider=provider,
            batch_size=2,
        )

    assert db.timeline[:2] == ["provider:2", "provider:2"]
    assert db.timeline[2] == "db:delete-old"
    assert db.batch_sizes == [2, 2]
    assert db.expunge_count == 2
    assert "db:rollback" not in db.timeline
    assert document.status == DocumentStatus.EMBEDDING.value


def test_loading_chunks_releases_the_read_transaction_before_provider_calls() -> None:
    chunks = _chunks(2)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        user_id=chunks[0].user_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession(chunks=chunks)
    provider = BatchProvider(db)

    embedding_service.embed_document_chunks(
        db,
        document,
        provider=provider,
        batch_size=2,
    )

    assert db.timeline[:6] == [
        "db:load-chunks",
        "db:rollback",
        "provider:2",
        "db:load-chunks",
        "db:rollback",
        "db:delete-old",
    ]


def test_stored_chunks_are_keyset_scanned_in_provider_sized_batches() -> None:
    chunks = _chunks(5)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        user_id=chunks[0].user_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession(
        chunk_batches=[
            chunks[:2],
            chunks[2:4],
            chunks[4:],
            [],
        ]
    )
    provider = BatchProvider(db)

    persisted = embedding_service.embed_document_chunks(
        db,
        document,
        provider=provider,
        batch_size=2,
    )

    assert persisted == 5
    assert [len(call) for call in provider.calls] == [2, 2, 1]
    assert db.batch_sizes == [2, 2, 1]
    assert len(db.select_statements) == 4
    assert "document_chunks.chunk_index >" not in str(
        db.select_statements[0]
    )
    assert all(
        "document_chunks.chunk_index >" in str(statement)
        for statement in db.select_statements[1:]
    )
    assert all(
        statement._limit_clause.value == 2
        for statement in db.select_statements
    )


def test_large_vector_payload_rolls_from_memory_to_anonymous_tempfile(
    monkeypatch,
) -> None:
    chunks = _chunks(2)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession()
    provider = BatchProvider(db)
    real_spooled_file = tempfile.SpooledTemporaryFile
    created_spools = []

    def tracked_spooled_file(*args, **kwargs):
        spool = real_spooled_file(*args, **kwargs)
        created_spools.append(spool)
        return spool

    monkeypatch.setattr(
        embedding_service,
        "EMBEDDING_SPOOL_MEMORY_BYTES",
        1,
    )
    monkeypatch.setattr(
        embedding_service.tempfile,
        "SpooledTemporaryFile",
        tracked_spooled_file,
    )

    embedding_service.embed_document_chunks(
        db,
        document,
        chunks=chunks,
        provider=provider,
        batch_size=2,
    )

    assert len(created_spools) == 1
    assert created_spools[0]._rolled is True
    assert created_spools[0].closed is True


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_invalid_embedding_batch_size_is_rejected_before_provider_or_database(
    batch_size,
) -> None:
    chunks = _chunks(1)
    document = SimpleNamespace(
        id=chunks[0].document_id,
        status=DocumentStatus.CHUNKING.value,
    )
    db = BatchSession()
    provider = BatchProvider(db)

    with pytest.raises(ValueError, match="positive integer"):
        embedding_service.embed_document_chunks(
            db,
            document,
            chunks=chunks,
            provider=provider,
            batch_size=batch_size,
        )

    assert provider.calls == []
    assert db.timeline == []
