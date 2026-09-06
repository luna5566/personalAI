from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.chunker import ChunkData
from app.services import chunking_service


def _chunk_data(count: int):
    for index in range(count):
        yield ChunkData(
            chunk_index=index,
            content=f"chunk-{index}",
            start_offset=index * 10,
            end_offset=index * 10 + 7,
            char_count=7,
        )


class BatchSession:
    def __init__(self, generated, *, fail_flush_at=None) -> None:
        self.generated = generated
        self.fail_flush_at = fail_flush_at
        self.timeline = []
        self.batch_sizes = []
        self.flush_count = 0
        self.expunge_count = 0

    def execute(self, statement):
        self.timeline.append("delete-old")

    def add_all(self, values):
        values = list(values)
        self.batch_sizes.append(len(values))
        self.timeline.append(f"add:{len(values)}")

    def flush(self):
        self.flush_count += 1
        self.timeline.append(
            f"flush:{self.flush_count}:generated:{len(self.generated)}"
        )
        if self.flush_count == self.fail_flush_at:
            raise RuntimeError("chunk flush failed")

    def expunge(self, value):
        self.expunge_count += 1


def test_recreate_document_chunks_flushes_and_detaches_each_batch(
    monkeypatch,
) -> None:
    generated = []

    def chunks(text):
        for item in _chunk_data(5):
            generated.append(item.chunk_index)
            yield item

    db = BatchSession(generated)
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        raw_text="source",
        cleaned_text="source",
    )
    monkeypatch.setattr(chunking_service, "iter_text_chunks", chunks)

    persisted = chunking_service.recreate_document_chunks(
        db,
        document,
        batch_size=2,
    )

    assert persisted == 5
    assert db.batch_sizes == [2, 2, 1]
    assert db.expunge_count == 5
    assert db.timeline == [
        "delete-old",
        "add:2",
        "flush:1:generated:2",
        "add:2",
        "flush:2:generated:4",
        "add:1",
        "flush:3:generated:5",
    ]


def test_chunk_batch_failure_leaves_rollback_to_caller(monkeypatch) -> None:
    generated = []
    db = BatchSession(generated, fail_flush_at=2)
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        raw_text="source",
        cleaned_text="source",
    )
    monkeypatch.setattr(
        chunking_service,
        "iter_text_chunks",
        lambda text: _chunk_data(4),
    )

    with pytest.raises(RuntimeError, match="chunk flush failed"):
        chunking_service.recreate_document_chunks(
            db,
            document,
            batch_size=2,
        )

    assert db.batch_sizes == [2, 2]
    assert db.expunge_count == 2
    assert "rollback" not in db.timeline


def test_existing_cleaned_text_is_not_cleaned_again(monkeypatch) -> None:
    db = BatchSession([])
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        raw_text="raw source",
        cleaned_text="already cleaned",
    )
    seen = []
    monkeypatch.setattr(
        chunking_service,
        "clean_text",
        lambda text: (_ for _ in ()).throw(
            AssertionError("cleaned text must be reused")
        ),
    )
    monkeypatch.setattr(
        chunking_service,
        "iter_text_chunks",
        lambda text: seen.append(text) or iter(()),
    )

    persisted = chunking_service.recreate_document_chunks(db, document)

    assert persisted == 0
    assert seen == ["already cleaned"]


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_invalid_chunk_batch_size_fails_before_database_work(
    batch_size,
) -> None:
    db = BatchSession([])
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        raw_text="source",
        cleaned_text="source",
    )

    with pytest.raises(ValueError, match="positive integer"):
        chunking_service.recreate_document_chunks(
            db,
            document,
            batch_size=batch_size,
        )

    assert db.timeline == []
