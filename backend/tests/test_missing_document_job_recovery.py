from types import SimpleNamespace
from uuid import uuid4

from app.models.document import DocumentStatus
from app.models.job import JobType
from app.services import job_service


class MissingDocumentSession:
    def __init__(self, documents) -> None:
        self.documents = documents
        self.statement = None

    def scalars(self, statement):
        self.statement = statement
        return self.documents


def test_missing_document_jobs_are_added_without_committing(monkeypatch) -> None:
    documents = [
        SimpleNamespace(id=uuid4(), user_id=uuid4()),
        SimpleNamespace(id=uuid4(), user_id=uuid4()),
    ]
    db = MissingDocumentSession(documents)
    added = []
    monkeypatch.setattr(
        job_service,
        "add_job",
        lambda *args, **kwargs: added.append((args, kwargs)),
    )

    count = job_service.add_missing_document_jobs(db, limit=7)

    assert count == 2
    assert added == [
        ((db, document.user_id, document.id, JobType.INDEX_DOCUMENT), {})
        for document in documents
    ]
    statement = db.statement
    assert statement._limit_clause.value == 7
    assert statement._for_update_arg.skip_locked is True
    params = statement.compile().params.values()
    assert DocumentStatus.UPLOADED.value in params
    assert JobType.INDEX_DOCUMENT.value in params


def test_missing_document_job_recovery_skips_zero_capacity() -> None:
    db = MissingDocumentSession([])

    assert job_service.add_missing_document_jobs(db, limit=0) == 0
    assert db.statement is None
