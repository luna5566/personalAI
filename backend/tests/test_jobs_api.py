import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.request_limits import (
    JOB_ERROR_MESSAGE_MAX_LENGTH,
    JOB_MESSAGE_MAX_LENGTH,
)
from app.models.job import Job, JobStatus, JobType
from app.schemas.job import JobRead
from app.services import job_service


def test_job_history_is_filtered_by_user_status_and_type_before_pagination() -> None:
    db = MagicMock()
    db.scalar.return_value = 42
    db.execute.return_value = []
    user_id = uuid4()

    jobs, total = job_service.list_jobs(
        db,
        user_id,
        page=2,
        page_size=20,
        status=JobStatus.FAILED,
        job_type=JobType.INDEX_DOCUMENT,
    )

    assert jobs == []
    assert total == 42
    statement = db.execute.call_args.args[0]
    params = statement.compile().params.values()
    assert user_id in params
    assert JobStatus.FAILED.value in params
    assert JobType.INDEX_DOCUMENT.value in params
    assert statement._offset_clause.value == 20
    assert statement._limit_clause.value == 20
    sql = str(statement)
    assert (
        "ORDER BY jobs.updated_at DESC, jobs.created_at DESC, jobs.id DESC"
        in sql
    )
    select_clause = sql.split("FROM jobs", maxsplit=1)[0]
    assert "left(jobs.message" in select_clause
    assert "left(jobs.error_message" in select_clause
    assert "jobs.run_token" not in select_clause
    assert "jobs.configuration_fingerprint" not in select_clause
    assert JOB_MESSAGE_MAX_LENGTH in statement.compile().params.values()
    assert JOB_ERROR_MESSAGE_MAX_LENGTH in statement.compile().params.values()


def test_job_indexes_cover_recovery_and_default_history_order() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in Job.__table__.indexes
    }

    assert indexes["ix_jobs_recoverable_created_at_id"] == (
        "created_at",
        "id",
    )
    assert indexes["ix_jobs_user_updated_created_id"] == (
        "user_id",
        "updated_at",
        "created_at",
        "id",
    )
    recoverable_index = next(
        index
        for index in Job.__table__.indexes
        if index.name == "ix_jobs_recoverable_created_at_id"
    )
    assert str(
        recoverable_index.dialect_options["postgresql"]["where"]
    ) == "status IN ('pending', 'cancel_requested', 'running')"


def test_job_response_does_not_expose_configuration_fingerprint() -> None:
    now = datetime.now(timezone.utc)
    job = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        retry_of_job_id=None,
        job_type=JobType.REBUILD_ALL_EMBEDDINGS.value,
        configuration_fingerprint="credential-api-key-hash",
        status=JobStatus.PENDING.value,
        progress=0,
        message="等待处理",
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    payload = JobRead.model_validate(job).model_dump()

    assert "configuration_fingerprint" not in payload
    assert "credential-api-key-hash" not in str(payload)


@pytest.mark.parametrize(
    ("field", "length"),
    [
        ("message", JOB_MESSAGE_MAX_LENGTH + 1),
        ("error_message", JOB_ERROR_MESSAGE_MAX_LENGTH + 1),
    ],
)
def test_job_response_rejects_text_beyond_public_bounds(
    field: str,
    length: int,
) -> None:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "document_id": None,
        "retry_of_job_id": None,
        "job_type": JobType.INDEX_DOCUMENT.value,
        "status": JobStatus.FAILED.value,
        "progress": 100,
        "message": "失败",
        "error_message": "错误",
        "created_at": now,
        "updated_at": now,
    }
    values[field] = "x" * length

    with pytest.raises(ValidationError):
        JobRead.model_validate(SimpleNamespace(**values))


def test_job_heartbeat_updates_until_stopped(monkeypatch) -> None:
    touched = []
    first_touch = threading.Event()

    def touch(job_id, run_token):
        touched.append((job_id, run_token))
        first_touch.set()
        return True

    monkeypatch.setattr(job_service, "touch_running_job", touch)
    job_id = uuid4()
    run_token = uuid4()
    heartbeat = job_service.JobHeartbeat(
        job_id,
        run_token,
        interval_seconds=0.01,
    )

    heartbeat.start()
    assert first_touch.wait(timeout=1)
    heartbeat.stop()
    count_after_stop = len(touched)
    threading.Event().wait(0.03)

    assert touched
    assert set(touched) == {(job_id, run_token)}
    assert len(touched) == count_after_stop


def test_job_heartbeat_interval_stays_below_stale_threshold(monkeypatch) -> None:
    monkeypatch.setattr(job_service.settings, "stale_job_after_minutes", 1)

    heartbeat = job_service.JobHeartbeat(uuid4(), uuid4(), interval_seconds=600)

    assert heartbeat._interval_seconds == 20


def test_touch_job_updates_only_running_jobs(monkeypatch) -> None:
    captured = {}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            captured["statement"] = statement
            return SimpleNamespace(rowcount=1)

        def commit(self):
            captured["committed"] = True

    monkeypatch.setattr(job_service, "SessionLocal", FakeSession)
    job_id = uuid4()
    run_token = uuid4()

    assert job_service.touch_running_job(job_id, run_token) is True

    params = captured["statement"].compile().params.values()
    assert job_id in params
    assert run_token in params
    assert JobStatus.RUNNING.value in params
    assert captured["committed"] is True
