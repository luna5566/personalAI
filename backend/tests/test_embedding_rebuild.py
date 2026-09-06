from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import DocumentStatus
from app.models.job import JobStatus
from app.workers import document_pipeline


@pytest.fixture(autouse=True)
def allow_current_job_execution(monkeypatch):
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline,
        "_count_rebuild_documents",
        lambda db, **kwargs: len(db.documents),
    )
    monkeypatch.setattr(
        document_pipeline,
        "_iter_rebuild_documents",
        lambda db, **kwargs: iter(db.documents),
    )


class FakeSession:
    def __init__(self, job, documents, chunk_results) -> None:
        self.job = job
        self.documents = documents
        self.chunk_results = list(chunk_results)
        self.scalar_calls = 0
        self.rolled_back = False
        self.connection_checked_out = True
        self.expunge_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, model, object_id):
        return self.job

    def scalars(self, statement):
        self.connection_checked_out = True
        self.scalar_calls += 1
        return self.chunk_results.pop(0)

    def scalar(self, statement):
        self.connection_checked_out = True
        if "document_chunks" in str(statement):
            chunks = self.chunk_results.pop(0)
            return chunks[0].id if chunks else None
        return self.job.status

    def add(self, value):
        return None

    def commit(self):
        self.connection_checked_out = False

    def flush(self):
        return None

    def refresh(self, value):
        self.connection_checked_out = True
        return None

    def rollback(self):
        self.rolled_back = True
        self.connection_checked_out = False

    def expunge_all(self):
        self.expunge_calls += 1

    def execute(self, statement, params=None):
        return SimpleNamespace(rowcount=1)


class FakeLockConnection:
    def __init__(self) -> None:
        self.calls = []
        self.commits = 0
        self.closed = False
        self.invalidated = False

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))

    def scalar(self, statement, params=None):
        self.calls.append((str(statement), params))
        return True

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    def invalidate(self):
        self.invalidated = True


class FakeLockEngine:
    def __init__(self) -> None:
        self.connection = FakeLockConnection()

    def connect(self):
        return self.connection


def _document():
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        title="索引缺失资料",
        status=DocumentStatus.INDEXED.value,
        raw_text="可以重新切片的正文",
        cleaned_text="可以重新切片的正文",
        error_message=None,
    )


def test_indexed_document_without_chunks_is_recreated(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=0,
        status=JobStatus.PENDING.value,
    )
    document = _document()
    chunk = SimpleNamespace(id=uuid4())
    session = FakeSession(job, [document], [[]])
    updates = []
    recreated = []
    embedded = []

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "complete_running_job",
        lambda *args, **kwargs: updates.append({"status": JobStatus.SUCCESS}),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: updates.append(
            {"status": JobStatus.FAILED, **kwargs}
        ),
    )
    monkeypatch.setattr(
        document_pipeline.chunking_service,
        "recreate_document_chunks",
        lambda db, value: recreated.append(value.id) or 1,
    )
    monkeypatch.setattr(
        document_pipeline.embedding_service,
        "embed_document_chunks",
        lambda db, value, provider: (
            embedded.append((value.id, provider.index_id))
            if not db.connection_checked_out
            else (_ for _ in ()).throw(
                AssertionError("provider called with a checked-out connection")
            )
        ),
    )

    document_pipeline.rebuild_embeddings(job.id, document.user_id)

    assert recreated == [document.id]
    assert embedded == [(document.id, "local_hash:1536")]
    assert document.status == DocumentStatus.INDEXED.value
    assert updates[-1]["status"] == JobStatus.SUCCESS


def test_rebuild_failure_marks_document_and_job_failed(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=0,
        status=JobStatus.PENDING.value,
    )
    document = _document()
    chunk = SimpleNamespace(id=uuid4())
    session = FakeSession(job, [document], [[chunk]])
    updates = []

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "complete_running_job",
        lambda *args, **kwargs: updates.append({"status": JobStatus.SUCCESS}),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: updates.append(
            {"status": JobStatus.FAILED, "progress": 100, **kwargs}
        ),
    )
    monkeypatch.setattr(
        document_pipeline.embedding_service,
        "embed_document_chunks",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: document,
    )

    document_pipeline.rebuild_embeddings(job.id, document.user_id)

    assert document.status == DocumentStatus.FAILED.value
    assert document.error_message == (
        "重建索引失败，请检查 Embedding Provider 配置后重试"
    )
    assert "provider down" not in document.error_message
    assert updates[-1]["status"] == JobStatus.FAILED
    assert updates[-1]["progress"] == 100
    assert "provider down" not in updates[-1]["error_message"]


def test_global_rebuild_processes_documents_from_multiple_users(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=0,
        status=JobStatus.PENDING.value,
    )
    first_document = _document()
    second_document = _document()
    first_chunk = SimpleNamespace(id=uuid4())
    second_chunk = SimpleNamespace(id=uuid4())
    session = FakeSession(
        job,
        [first_document, second_document],
        [[first_chunk], [second_chunk]],
    )
    embedded_users = []
    updates = []
    lock_engine = FakeLockEngine()

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(document_pipeline, "engine", lock_engine)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "complete_running_job",
        lambda *args, **kwargs: updates.append({"status": JobStatus.SUCCESS}),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: updates.append(
            {"status": JobStatus.FAILED, **kwargs}
        ),
    )
    monkeypatch.setattr(
        document_pipeline.embedding_service,
        "embed_document_chunks",
        lambda db, document, provider: embedded_users.append(
            document.user_id
        ),
    )

    document_pipeline.rebuild_embeddings(job.id, None)

    assert embedded_users == [first_document.user_id, second_document.user_id]
    assert first_document.user_id != second_document.user_id
    assert updates[-1]["status"] == JobStatus.SUCCESS
    assert [call[0] for call in lock_engine.connection.calls] == [
        "SELECT pg_advisory_lock(:lock_id)",
        "SELECT pg_advisory_unlock(:lock_id)",
    ]
    assert lock_engine.connection.commits == 2
    assert lock_engine.connection.closed is True
    assert lock_engine.connection.invalidated is False


def test_duplicate_global_worker_stops_after_original_job_finishes(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=5,
        status=JobStatus.RUNNING.value,
    )
    session = FakeSession(job, [], [])
    updates = []
    lock_engine = FakeLockEngine()

    def finish_job(value):
        value.status = JobStatus.SUCCESS.value

    session.refresh = finish_job
    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(document_pipeline, "engine", lock_engine)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: updates.append(kwargs),
    )

    document_pipeline.rebuild_embeddings(job.id, None)

    assert session.scalar_calls == 0
    assert len(updates) == 1
    assert lock_engine.connection.closed is True


def test_rebuild_failure_summary_keeps_only_three_samples(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=0,
        status=JobStatus.PENDING.value,
    )
    documents = []
    for index in range(10):
        document = _document()
        document.title = f"document-{index}"
        document.raw_text = ""
        document.cleaned_text = ""
        documents.append(document)
    session = FakeSession(job, documents, [])
    failures = []

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "complete_running_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: failures.append(kwargs),
    )

    document_pipeline.rebuild_embeddings(job.id, documents[0].user_id)

    assert len(failures) == 1
    failure = failures[0]
    assert "失败 10 份" in failure["message"]
    assert "document-0" in failure["error_message"]
    assert "document-1" in failure["error_message"]
    assert "document-2" in failure["error_message"]
    assert "document-3" not in failure["error_message"]
    assert "另有 7 份失败" in failure["error_message"]


def test_rebuild_cancellation_rolls_back_current_document(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        progress=0,
        status=JobStatus.PENDING.value,
    )
    document = _document()
    chunk = SimpleNamespace(id=uuid4())
    session = FakeSession(job, [document], [[chunk]])
    checkpoints = []
    embedded = []
    cancelled = []

    def cancellation_checkpoint(db, job_id, run_token):
        checkpoints.append(job_id)
        if len(checkpoints) == 3:
            raise document_pipeline.job_service.JobCancelledError()

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        cancellation_checkpoint,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "mark_job_cancelled",
        lambda db, job_id, run_token, message: cancelled.append((job_id, message)),
    )
    monkeypatch.setattr(
        document_pipeline.embedding_service,
        "embed_document_chunks",
        lambda *args, **kwargs: embedded.append(document.id),
    )

    document_pipeline.rebuild_embeddings(job.id, document.user_id)

    assert embedded == []
    assert session.rolled_back is True
    assert cancelled == [(job.id, "任务已取消，已重建 0 份资料")]
