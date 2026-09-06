import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.api.routes import jobs as jobs_routes
from app.core.request_limits import (
    JOB_ERROR_MESSAGE_MAX_LENGTH,
    JOB_MESSAGE_MAX_LENGTH,
)
from app.models.document import DocumentStatus
from app.models.job import JobStatus, JobType
from app.services import job_service
from app.workers import job_recovery
from app.workers import document_pipeline


class ControlSession:
    def __init__(self, scalar_values, document=None) -> None:
        self.scalar_values = iter(scalar_values)
        self.document = document
        self.added = []
        self.committed = False

    def scalar(self, statement):
        return next(self.scalar_values)

    def get(self, model, object_id):
        return self.document

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def refresh(self, value):
        return None


def test_pending_document_job_cancels_job_and_document() -> None:
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.UPLOADED.value,
        error_message="old error",
    )
    job = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=document.id,
        job_type=JobType.INDEX_DOCUMENT.value,
        status=JobStatus.PENDING.value,
        message="等待处理",
        error_message="old error",
    )
    db = ControlSession([job], document=document)

    result = job_service.cancel_job(db, job.user_id, job.id)

    assert result.status == JobStatus.CANCELLED.value
    assert result.message == "任务已取消"
    assert document.status == DocumentStatus.CANCELLED.value
    assert document.error_message is None
    assert db.committed is True


def test_running_job_records_cancel_request() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        status=JobStatus.RUNNING.value,
        message="处理中",
        error_message=None,
    )
    db = ControlSession([job])

    result = job_service.cancel_job(db, job.user_id, job.id)

    assert result.status == JobStatus.CANCEL_REQUESTED.value
    assert result.message == "正在取消任务"


def test_failure_transition_does_not_overwrite_cancel_request() -> None:
    job_id = uuid4()
    run_token = uuid4()

    class TransitionSession:
        def execute(self, statement):
            if statement.is_select:
                return SimpleNamespace(
                    one_or_none=lambda: (
                        JobStatus.CANCEL_REQUESTED.value,
                        run_token,
                    )
                )
            return SimpleNamespace(rowcount=0)

        def commit(self):
            return None

        def scalar(self, statement):
            return JobStatus.CANCEL_REQUESTED.value

    with pytest.raises(job_service.JobCancelledError, match="任务已取消"):
        job_service.fail_active_job(
            TransitionSession(),
            job_id,
            run_token,
            message="处理失败",
            error_message="provider down",
        )


def test_failure_transition_bounds_text_before_update() -> None:
    job_id = uuid4()
    run_token = uuid4()
    statements = []
    job = SimpleNamespace(id=job_id, run_token=None)

    class TransitionSession:
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)

        def commit(self):
            return None

        def get(self, model, object_id):
            return job

        def refresh(self, value):
            return None

    job_service.fail_active_job(
        TransitionSession(),
        job_id,
        run_token,
        message="m" * (JOB_MESSAGE_MAX_LENGTH + 100),
        error_message="e" * (JOB_ERROR_MESSAGE_MAX_LENGTH + 100),
    )

    params = statements[0].compile().params.values()
    assert "m" * JOB_MESSAGE_MAX_LENGTH in params
    assert "e" * JOB_ERROR_MESSAGE_MAX_LENGTH in params
    assert "m" * (JOB_MESSAGE_MAX_LENGTH + 100) not in params
    assert "e" * (JOB_ERROR_MESSAGE_MAX_LENGTH + 100) not in params


def test_start_transition_does_not_overwrite_cancelled_job() -> None:
    job_id = uuid4()
    run_token = uuid4()

    class TransitionSession:
        def execute(self, statement):
            return SimpleNamespace(rowcount=0)

        def commit(self):
            return None

        def scalar(self, statement):
            return JobStatus.CANCELLED.value

    with pytest.raises(job_service.JobCancelledError, match="任务已取消"):
        job_service.start_job(
            TransitionSession(),
            job_id,
            run_token,
            progress=10,
            message="正在解析资料",
        )


def test_start_transition_rejects_job_claimed_by_recovery() -> None:
    job_id = uuid4()
    run_token = uuid4()

    class TransitionSession:
        def execute(self, statement):
            return SimpleNamespace(rowcount=0)

        def commit(self):
            return None

        def scalar(self, statement):
            return JobStatus.RUNNING.value

    with pytest.raises(job_service.JobClaimConflictError, match="其他 worker"):
        job_service.start_job(
            TransitionSession(),
            job_id,
            run_token,
            progress=10,
            message="正在解析资料",
        )


def test_start_and_resume_claim_distinct_job_states() -> None:
    job = SimpleNamespace(id=uuid4(), run_token=None)
    statements = []
    first_token = uuid4()
    recovered_token = uuid4()

    class ClaimSession:
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)

        def commit(self):
            return None

        def get(self, model, object_id):
            return job

        def refresh(self, value):
            return None

    db = ClaimSession()
    job_service.start_job(
        db,
        job.id,
        first_token,
        progress=10,
        message="首次领取",
    )
    job_service.resume_job(
        db,
        job.id,
        recovered_token,
        progress=20,
        message="恢复续跑",
    )

    expected_statuses = [
        statement._where_criteria[1].right.value for statement in statements
    ]
    assert expected_statuses == [
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value,
    ]


def test_old_run_token_cannot_update_reclaimed_job() -> None:
    job_id = uuid4()
    old_token = uuid4()
    current_token = uuid4()

    class TransitionSession:
        def execute(self, statement):
            if statement.is_select:
                return SimpleNamespace(
                    one_or_none=lambda: (
                        JobStatus.RUNNING.value,
                        current_token,
                    )
                )
            return SimpleNamespace(rowcount=0)

        def commit(self):
            return None

    with pytest.raises(job_service.JobClaimConflictError, match="执行权已转移"):
        job_service.update_running_job(
            TransitionSession(),
            job_id,
            old_token,
            progress=45,
            message="旧 worker 更新",
        )


def test_retry_creates_new_job_and_preserves_original(monkeypatch) -> None:
    document = SimpleNamespace(id=uuid4())
    original = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=document.id,
        job_type=JobType.INDEX_DOCUMENT.value,
        status=JobStatus.FAILED.value,
    )
    retry = SimpleNamespace(id=uuid4())
    db = ControlSession([original, None], document=document)
    created = []
    monkeypatch.setattr(
        job_service,
        "create_job",
        lambda session, user_id, document_id, job_type, retry_of_job_id: created.append(
            (user_id, document_id, job_type, retry_of_job_id)
        )
        or retry,
    )

    result, preserved = job_service.create_retry_job(
        db,
        original.user_id,
        original.id,
    )

    assert result is retry
    assert preserved is original
    assert original.status == JobStatus.FAILED.value
    assert created == [
        (
            original.user_id,
            original.document_id,
            JobType.INDEX_DOCUMENT,
            original.id,
        )
    ]


def test_retry_rejects_when_equivalent_job_is_active() -> None:
    original = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        status=JobStatus.CANCELLED.value,
    )
    db = ControlSession([original, uuid4()])

    with pytest.raises(job_service.JobConflictError, match="正在处理"):
        job_service.create_retry_job(db, original.user_id, original.id)


def test_recovery_finishes_cancel_requested_job_without_dispatch(monkeypatch) -> None:
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.PARSING.value,
        error_message=None,
    )
    job = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=document.id,
        job_type=JobType.INDEX_DOCUMENT.value,
        status=JobStatus.CANCEL_REQUESTED.value,
        message="正在取消任务",
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )

    class RecoverySession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def scalars(self, statement):
            return [job]

        def execute(self, statement, parameters=None):
            return None

        def get(self, model, object_id):
            return document

        def add(self, value):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(job_recovery, "SessionLocal", RecoverySession)
    monkeypatch.setattr(
        job_recovery.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda *args: None,
    )
    monkeypatch.setattr(
        job_recovery.job_service,
        "add_missing_document_jobs",
        lambda *args: 0,
    )

    assert job_recovery.claim_recoverable_jobs() == []
    assert job.status == JobStatus.CANCELLED.value
    assert document.status == DocumentStatus.CANCELLED.value


def test_recovery_rotates_execution_token_when_claiming_pending_job(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        status=JobStatus.PENDING.value,
        run_token=None,
        message="等待处理",
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )

    captured = {}
    reconciled = []

    class RecoverySession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def scalars(self, statement):
            captured["statement"] = statement
            return [job]

        def execute(self, statement, parameters=None):
            captured["timeout_statement"] = statement
            captured["timeout_parameters"] = parameters
            return None

        def add(self, value):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(job_recovery, "SessionLocal", RecoverySession)
    monkeypatch.setattr(
        job_recovery.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda db, owner: reconciled.append((db, owner)),
    )
    monkeypatch.setattr(
        job_recovery.job_service,
        "add_missing_document_jobs",
        lambda *args: 0,
    )
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_batch_size",
        7,
    )
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_statement_timeout_seconds",
        1.25,
    )

    claimed = job_recovery.claim_recoverable_jobs(limit=3)

    assert len(claimed) == 1
    assert job.status == JobStatus.RUNNING.value
    assert job.run_token is not None
    assert claimed[0].run_token == job.run_token
    assert len(reconciled) == 1
    assert reconciled[0][1] == job_recovery.settings.runtime_settings_admin_user_id
    assert captured["statement"]._limit_clause.value == 3
    recovery_sql = str(captured["statement"])
    assert (
        "jobs.status IN ('pending', 'cancel_requested', 'running')"
        in recovery_sql
    )
    assert "ORDER BY jobs.created_at, jobs.id" in recovery_sql
    assert "set_config('statement_timeout'" in str(captured["timeout_statement"])
    assert captured["timeout_parameters"] == {"timeout_ms": "1250"}


def test_startup_purges_history_before_claiming_jobs(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        job_recovery.maintenance_service,
        "purge_expired_data",
        lambda: calls.append("maintenance"),
    )
    monkeypatch.setattr(
        job_recovery,
        "claim_recoverable_jobs",
        lambda *, limit: calls.append("claim") or [],
    )

    async def run_schedule():
        assert await job_recovery.schedule_recoverable_jobs() == []

    asyncio.run(run_schedule())

    assert calls == ["maintenance", "claim"]


def test_document_worker_stops_after_parse_when_cancelled(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.PENDING.value,
    )
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.UPLOADED.value,
        raw_text=None,
        cleaned_text=None,
        metadata_={},
        error_message=None,
    )
    checkpoints = []
    chunk_calls = []
    cancelled = []

    class WorkerSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return job

        def add(self, value):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    def cancellation_checkpoint(db, job_id, run_token):
        checkpoints.append(job_id)
        if len(checkpoints) == 1:
            raise job_service.JobCancelledError()

    monkeypatch.setattr(document_pipeline, "SessionLocal", WorkerSession)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: document,
    )
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
        "raise_if_cancel_requested",
        lambda *args: None,
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
        document_pipeline.parsing_service,
        "parse_document",
        lambda value: SimpleNamespace(raw_text="parsed text", metadata={}),
    )
    monkeypatch.setattr(
        document_pipeline.chunking_service,
        "recreate_document_chunks",
        lambda *args: chunk_calls.append(True),
    )

    document_pipeline.process_document(job.id, document.id)

    assert chunk_calls == []
    assert document.status == DocumentStatus.CANCELLED.value
    assert cancelled == [(job.id, "资料处理已取消")]


def test_late_document_worker_exits_without_overwriting_recovery(monkeypatch) -> None:
    job = SimpleNamespace(id=uuid4(), status=JobStatus.RUNNING.value)
    document = SimpleNamespace(
        id=uuid4(),
        status=DocumentStatus.UPLOADED.value,
    )
    parsed = []
    failures = []

    class WorkerSession:
        def __init__(self):
            self.rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return job

        def rollback(self):
            self.rolled_back = True

    session = WorkerSession()
    monkeypatch.setattr(document_pipeline, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: document,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_cancel_requested",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            job_service.JobClaimConflictError("任务已由其他 worker 领取")
        ),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: failures.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.parsing_service,
        "parse_document",
        lambda value: parsed.append(value),
    )

    document_pipeline.process_document(job.id, document.id)

    assert session.rolled_back is True
    assert parsed == []
    assert failures == []
    assert document.status == DocumentStatus.UPLOADED.value


def test_retry_route_dispatches_new_document_worker(monkeypatch) -> None:
    user_id = uuid4()
    document_id = uuid4()
    original = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        job_type=JobType.INDEX_DOCUMENT.value,
        status=JobStatus.FAILED.value,
    )
    now = datetime.now(timezone.utc)
    retry = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        document_id=document_id,
        retry_of_job_id=original.id,
        job_type=JobType.INDEX_DOCUMENT.value,
        status=JobStatus.PENDING.value,
        progress=0,
        message="等待处理",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(
        jobs_routes.job_service,
        "get_job",
        lambda *args: original,
    )
    monkeypatch.setattr(
        jobs_routes.job_service,
        "create_retry_job",
        lambda *args: (retry, original),
    )

    result = jobs_routes.retry_job(
        original.id,
        background_tasks,
        MagicMock(),
        user_id,
    )

    assert isinstance(result, job_service.JobView)
    assert result.id == retry.id
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is jobs_routes.run_job_with_worker_limit
    assert task.args == (
        jobs_routes.process_document,
        retry.id,
        document_id,
    )


def test_retry_global_rebuild_records_current_configuration(monkeypatch) -> None:
    user_id = uuid4()
    original = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        document_id=None,
        job_type=JobType.REBUILD_ALL_EMBEDDINGS.value,
        status=JobStatus.FAILED.value,
    )
    now = datetime.now(timezone.utc)
    retry = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        document_id=None,
        retry_of_job_id=original.id,
        job_type=JobType.REBUILD_ALL_EMBEDDINGS.value,
        status=JobStatus.PENDING.value,
        progress=0,
        message="等待处理",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    created = []
    reconciled = []
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(jobs_routes.job_service, "get_job", lambda *args: original)
    monkeypatch.setattr(
        jobs_routes.settings_service,
        "ensure_runtime_settings_access",
        lambda value: None,
    )
    monkeypatch.setattr(
        jobs_routes.settings_service,
        "embedding_configuration_fingerprint",
        lambda: "current-fingerprint",
    )
    monkeypatch.setattr(
        jobs_routes.job_service,
        "create_retry_job",
        lambda *args, **kwargs: created.append((args, kwargs))
        or (retry, original),
    )
    monkeypatch.setattr(
        jobs_routes.embedding_configuration_service,
        "reconcile_embedding_configuration",
        lambda db, owner: reconciled.append((db, owner)),
    )
    db = MagicMock()

    result = jobs_routes.retry_job(
        original.id,
        background_tasks,
        db,
        user_id,
    )

    assert isinstance(result, job_service.JobView)
    assert result.id == retry.id
    assert created[0][1] == {
        "configuration_fingerprint": "current-fingerprint"
    }
    assert reconciled == [(db, user_id)]
    task = background_tasks.tasks[0]
    assert task.func is jobs_routes.run_job_with_worker_limit
    assert task.args == (
        jobs_routes.rebuild_embeddings,
        retry.id,
        None,
    )
