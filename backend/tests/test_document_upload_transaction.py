import asyncio
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, UploadFile

from app.api.routes import documents
from app.models.document import DocumentStatus


class UploadSession:
    def __init__(
        self,
        *,
        commit_error=None,
        refresh_error=None,
        rollback_error=None,
    ) -> None:
        self.commit_error = commit_error
        self.refresh_error = refresh_error
        self.rollback_error = rollback_error
        self.events = []

    def commit(self):
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error

    def refresh(self, value):
        self.events.append(("refresh", value))
        if self.refresh_error is not None:
            raise self.refresh_error


def _upload() -> UploadFile:
    return UploadFile(filename="example.txt", file=BytesIO(b"content"))


def _call_upload(db, background_tasks):
    return asyncio.run(
        documents.upload_document(
            background_tasks,
            db,
            uuid4(),
            file=_upload(),
            title=None,
            source_type=None,
            tags=None,
        )
    )


def _mock_saved_upload(monkeypatch) -> None:
    async def save_upload(*args, **kwargs):
        return "documents/example.txt", 7

    monkeypatch.setattr(documents.storage_service, "save_upload", save_upload)


def test_upload_commits_document_and_job_together(monkeypatch) -> None:
    _mock_saved_upload(monkeypatch)
    document = SimpleNamespace(id=uuid4(), original_filename="example.txt")
    job = SimpleNamespace(id=uuid4())
    db = UploadSession()
    background_tasks = BackgroundTasks()
    added = []
    monkeypatch.setattr(
        documents.document_service,
        "add_file_document",
        lambda **kwargs: added.append(("document", kwargs["db"])) or document,
    )
    monkeypatch.setattr(
        documents.job_service,
        "add_job",
        lambda session, *args: added.append(("job", session)) or job,
    )

    result = _call_upload(db, background_tasks)

    assert result.document_id == document.id
    assert result.job_id == job.id
    assert result.status is DocumentStatus.UPLOADED
    assert added == [("document", db), ("job", db)]
    assert db.events == [
        "commit",
        ("refresh", document),
        ("refresh", job),
    ]
    task = background_tasks.tasks[0]
    assert task.func is documents.run_job_with_worker_limit
    assert task.is_async is True
    assert task.args == (documents.process_document, job.id, document.id)


def test_upload_flush_failure_rolls_back_and_removes_uncommitted_file(
    monkeypatch,
) -> None:
    _mock_saved_upload(monkeypatch)
    document = SimpleNamespace(id=uuid4(), original_filename="example.txt")
    db = UploadSession()
    deleted = []
    monkeypatch.setattr(
        documents.document_service,
        "add_file_document",
        lambda **kwargs: document,
    )
    monkeypatch.setattr(
        documents.job_service,
        "add_job",
        lambda *args: (_ for _ in ()).throw(RuntimeError("job flush failed")),
    )
    monkeypatch.setattr(
        documents.storage_service,
        "delete_key",
        lambda key: deleted.append(key),
    )

    with pytest.raises(RuntimeError, match="job flush failed"):
        _call_upload(db, BackgroundTasks())

    assert db.events == ["rollback"]
    assert deleted == ["documents/example.txt"]


def test_upload_commit_failure_retains_file_for_ambiguous_outcome(
    monkeypatch,
) -> None:
    _mock_saved_upload(monkeypatch)
    document = SimpleNamespace(id=uuid4(), original_filename="example.txt")
    job = SimpleNamespace(id=uuid4())
    db = UploadSession(commit_error=RuntimeError("commit outcome unknown"))
    deleted = []
    monkeypatch.setattr(
        documents.document_service,
        "add_file_document",
        lambda **kwargs: document,
    )
    monkeypatch.setattr(documents.job_service, "add_job", lambda *args: job)
    monkeypatch.setattr(
        documents.storage_service,
        "delete_key",
        lambda key: deleted.append(key),
    )

    with pytest.raises(RuntimeError, match="outcome unknown"):
        _call_upload(db, BackgroundTasks())

    assert db.events == ["commit", "rollback"]
    assert deleted == []


def test_upload_rollback_failure_does_not_mask_flush_error_or_skip_cleanup(
    monkeypatch,
) -> None:
    _mock_saved_upload(monkeypatch)
    document = SimpleNamespace(id=uuid4(), original_filename="example.txt")
    db = UploadSession(rollback_error=RuntimeError("rollback unavailable"))
    deleted = []
    monkeypatch.setattr(
        documents.document_service,
        "add_file_document",
        lambda **kwargs: document,
    )
    monkeypatch.setattr(
        documents.job_service,
        "add_job",
        lambda *args: (_ for _ in ()).throw(RuntimeError("original flush error")),
    )
    monkeypatch.setattr(
        documents.storage_service,
        "delete_key",
        lambda key: deleted.append(key),
    )

    with pytest.raises(RuntimeError, match="original flush error"):
        _call_upload(db, BackgroundTasks())

    assert db.events == ["rollback"]
    assert deleted == ["documents/example.txt"]


def test_upload_refresh_failure_does_not_delete_committed_file(monkeypatch) -> None:
    _mock_saved_upload(monkeypatch)
    document = SimpleNamespace(id=uuid4(), original_filename="example.txt")
    job = SimpleNamespace(id=uuid4())
    db = UploadSession(refresh_error=RuntimeError("refresh failed"))
    deleted = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        documents.document_service,
        "add_file_document",
        lambda **kwargs: document,
    )
    monkeypatch.setattr(documents.job_service, "add_job", lambda *args: job)
    monkeypatch.setattr(
        documents.storage_service,
        "delete_key",
        lambda key: deleted.append(key),
    )

    with pytest.raises(RuntimeError, match="refresh failed"):
        _call_upload(db, background_tasks)

    assert db.events == ["commit", ("refresh", document)]
    assert deleted == []
    assert background_tasks.tasks == []
