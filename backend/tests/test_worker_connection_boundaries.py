from types import SimpleNamespace
from uuid import uuid4

from app.models.document import DocumentStatus
from app.models.job import JobStatus
from app.workers import document_pipeline


class WorkerBoundarySession:
    def __init__(self, job) -> None:
        self.job = job
        self.connection_checked_out = True
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, model, object_id):
        self.connection_checked_out = True
        self.events.append("get")
        return self.job

    def add(self, value):
        self.events.append("add")

    def commit(self):
        self.connection_checked_out = False
        self.events.append("commit")

    def rollback(self):
        self.connection_checked_out = False
        self.events.append("rollback")

    def flush(self):
        self.connection_checked_out = True
        self.events.append("flush")

    def expunge_all(self):
        self.events.append("expunge_all")


def test_document_worker_releases_connection_before_each_provider(
    monkeypatch,
) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.PENDING.value,
        run_token=None,
    )
    document = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status=DocumentStatus.UPLOADED.value,
        raw_text=None,
        cleaned_text=None,
        metadata_={},
        error_message=None,
    )
    chunk = SimpleNamespace(id=uuid4(), content="parsed text")
    db = WorkerBoundarySession(job)
    provider_events = []

    class Heartbeat:
        def __init__(self, *args):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    def database_checkpoint(*args, **kwargs):
        db.connection_checked_out = True

    def parse_document(value):
        assert db.connection_checked_out is False
        provider_events.append("parse")
        return SimpleNamespace(raw_text="parsed text", metadata={})

    def embed_document_chunks(*args, **kwargs):
        assert db.connection_checked_out is False
        provider_events.append("embedding")
        db.connection_checked_out = True

    def enrich_document(*args, **kwargs):
        assert db.connection_checked_out is False
        provider_events.append("enrichment")
        db.connection_checked_out = True

    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: db)
    monkeypatch.setattr(document_pipeline.job_service, "JobHeartbeat", Heartbeat)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: document,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_cancel_requested",
        database_checkpoint,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        database_checkpoint,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        database_checkpoint,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "update_running_job",
        database_checkpoint,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "complete_running_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.parsing_service,
        "parse_document",
        parse_document,
    )
    monkeypatch.setattr(
        document_pipeline.chunking_service,
        "recreate_document_chunks",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        document_pipeline.embedding_service,
        "embed_document_chunks",
        embed_document_chunks,
    )
    monkeypatch.setattr(
        document_pipeline.enrichment_service,
        "load_document_enrichment_chunks",
        lambda *args: [chunk],
    )
    monkeypatch.setattr(
        document_pipeline.enrichment_service,
        "enrich_document",
        enrich_document,
    )

    document_pipeline.process_document(job.id, document.id)

    assert provider_events == ["parse", "embedding", "enrichment"]
    assert db.events.count("expunge_all") == 2
    assert document.status == DocumentStatus.INDEXED.value
