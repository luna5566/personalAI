from dataclasses import dataclass
from datetime import datetime
import logging
import threading
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, load_only

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.pagination import offset_for_page
from app.core.request_limits import (
    JOB_ERROR_MESSAGE_MAX_LENGTH,
    JOB_MESSAGE_MAX_LENGTH,
)
from app.models.document import Document, DocumentSourceType, DocumentStatus
from app.models.job import Job, JobStatus, JobType

logger = logging.getLogger(__name__)
ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING.value,
    JobStatus.RUNNING.value,
    JobStatus.CANCEL_REQUESTED.value,
}
RETRYABLE_JOB_STATUSES = {
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}
TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCESS.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


@dataclass(frozen=True)
class JobView:
    id: UUID
    user_id: UUID
    document_id: UUID | None
    retry_of_job_id: UUID | None
    job_type: str
    status: str
    progress: int
    message: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class JobNotFoundError(ValueError):
    pass


class JobConflictError(ValueError):
    pass


class JobCancelledError(RuntimeError):
    pass


class JobClaimConflictError(JobConflictError):
    pass


def create_job(
    db: Session,
    user_id: UUID,
    document_id: UUID | None,
    job_type: JobType,
    *,
    retry_of_job_id: UUID | None = None,
    configuration_fingerprint: str | None = None,
) -> Job:
    job = add_job(
        db,
        user_id,
        document_id,
        job_type,
        retry_of_job_id=retry_of_job_id,
        configuration_fingerprint=configuration_fingerprint,
    )
    db.commit()
    db.refresh(job)
    return job


def add_job(
    db: Session,
    user_id: UUID,
    document_id: UUID | None,
    job_type: JobType,
    *,
    retry_of_job_id: UUID | None = None,
    configuration_fingerprint: str | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        document_id=document_id,
        retry_of_job_id=retry_of_job_id,
        job_type=job_type.value,
        configuration_fingerprint=configuration_fingerprint,
        status=JobStatus.PENDING.value,
        progress=0,
        message="等待处理",
    )
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, user_id: UUID, job_id: UUID) -> JobView | None:
    row = db.execute(
        _job_view_statement().where(
            Job.id == job_id,
            Job.user_id == user_id,
        )
    ).one_or_none()
    return _job_view_from_row(row) if row is not None else None


def add_missing_document_jobs(db: Session, limit: int) -> int:
    if limit <= 0:
        return 0
    existing_index_job = (
        select(Job.id)
        .where(
            Job.document_id == Document.id,
            Job.job_type == JobType.INDEX_DOCUMENT.value,
        )
        .exists()
    )
    documents = list(
        db.scalars(
            select(Document)
            .where(
                Document.status == DocumentStatus.UPLOADED.value,
                Document.source_type != DocumentSourceType.NOTE.value,
                ~existing_index_job,
            )
            .order_by(Document.created_at, Document.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for document in documents:
        add_job(
            db,
            document.user_id,
            document.id,
            JobType.INDEX_DOCUMENT,
        )
    return len(documents)


def cancel_job(db: Session, user_id: UUID, job_id: UUID) -> Job:
    job = db.scalar(
        select(Job)
        .options(
            load_only(
                Job.id,
                Job.user_id,
                Job.document_id,
                Job.retry_of_job_id,
                Job.job_type,
                Job.status,
                Job.progress,
                Job.created_at,
                Job.updated_at,
                raiseload=True,
            )
        )
        .where(Job.id == job_id, Job.user_id == user_id)
        .with_for_update()
    )
    if job is None:
        raise JobNotFoundError("任务不存在")
    if job.status in {
        JobStatus.CANCEL_REQUESTED.value,
        JobStatus.CANCELLED.value,
    }:
        job.message = (
            "正在取消任务"
            if job.status == JobStatus.CANCEL_REQUESTED.value
            else "任务已取消"
        )
        job.error_message = None
        return job
    if job.status == JobStatus.PENDING.value:
        job.status = JobStatus.CANCELLED.value
        job.run_token = None
        job.message = "任务已取消"
        job.error_message = None
        if job.job_type == JobType.INDEX_DOCUMENT.value and job.document_id is not None:
            document = db.get(Document, job.document_id)
            if document is not None:
                document.status = DocumentStatus.CANCELLED.value
                document.error_message = None
                db.add(document)
    elif job.status == JobStatus.RUNNING.value:
        job.status = JobStatus.CANCEL_REQUESTED.value
        job.message = "正在取消任务"
        job.error_message = None
    else:
        raise JobConflictError("只有等待中或运行中的任务可以取消")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_retry_job(
    db: Session,
    user_id: UUID,
    job_id: UUID,
    *,
    configuration_fingerprint: str | None = None,
) -> tuple[Job, Job]:
    original = db.scalar(
        select(Job)
        .options(
            load_only(
                Job.id,
                Job.user_id,
                Job.document_id,
                Job.retry_of_job_id,
                Job.job_type,
                Job.configuration_fingerprint,
                Job.status,
                raiseload=True,
            )
        )
        .where(Job.id == job_id, Job.user_id == user_id)
        .with_for_update()
    )
    if original is None:
        raise JobNotFoundError("任务不存在")
    if original.status not in RETRYABLE_JOB_STATUSES:
        raise JobConflictError("只有失败或已取消的任务可以重试")

    job_type = JobType(original.job_type)
    if job_type == JobType.INDEX_DOCUMENT:
        if original.document_id is None or db.get(Document, original.document_id) is None:
            raise JobConflictError("原资料已删除，无法重试")
        active_filter = Job.document_id == original.document_id
    else:
        active_filter = Job.job_type == original.job_type

    active_job_id = db.scalar(
        select(Job.id).where(
            Job.user_id == user_id,
            active_filter,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_job_id is not None:
        raise JobConflictError("已有同类任务正在处理")

    retry_configuration_fingerprint = (
        configuration_fingerprint
        if configuration_fingerprint is not None
        else getattr(original, "configuration_fingerprint", None)
    )
    if retry_configuration_fingerprint is None:
        retry = create_job(
            db,
            user_id,
            original.document_id,
            job_type,
            retry_of_job_id=original.id,
        )
    else:
        retry = create_job(
            db,
            user_id,
            original.document_id,
            job_type,
            retry_of_job_id=original.id,
            configuration_fingerprint=retry_configuration_fingerprint,
        )
    return retry, original


def cancellation_requested(db: Session, job_id: UUID) -> bool:
    current_status = db.scalar(select(Job.status).where(Job.id == job_id))
    return current_status in {
        JobStatus.CANCEL_REQUESTED.value,
        JobStatus.CANCELLED.value,
    }


def raise_if_cancel_requested(db: Session, job_id: UUID) -> None:
    if cancellation_requested(db, job_id):
        raise JobCancelledError("任务已取消")


def raise_if_job_stopped(db: Session, job_id: UUID, run_token: UUID) -> None:
    state = db.execute(
        select(Job.status, Job.run_token).where(Job.id == job_id)
    ).one_or_none()
    if state is None:
        raise JobNotFoundError("任务不存在")
    current_status, current_run_token = state
    if current_run_token != run_token:
        raise JobClaimConflictError("任务执行权已转移给其他 worker")
    if current_status in {
        JobStatus.CANCEL_REQUESTED.value,
        JobStatus.CANCELLED.value,
    }:
        raise JobCancelledError("任务已取消")
    if current_status != JobStatus.RUNNING.value:
        raise JobClaimConflictError("任务已不再运行")


def start_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    progress: int,
    message: str,
) -> Job:
    return _claim_job(
        db,
        job_id,
        run_token,
        expected_status=JobStatus.PENDING,
        match_run_token=False,
        progress=progress,
        message=message,
    )


def resume_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    progress: int,
    message: str,
) -> Job:
    return _claim_job(
        db,
        job_id,
        run_token,
        expected_status=JobStatus.RUNNING,
        match_run_token=True,
        progress=progress,
        message=message,
    )


def _claim_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    *,
    expected_status: JobStatus,
    match_run_token: bool,
    progress: int,
    message: str,
) -> Job:
    filters = [Job.id == job_id, Job.status == expected_status.value]
    if match_run_token:
        filters.append(Job.run_token == run_token)
    result = db.execute(
        update(Job)
        .where(*filters)
        .values(
            status=JobStatus.RUNNING.value,
            run_token=run_token,
            progress=max(0, min(progress, 100)),
            message=_bounded_job_message(message),
            error_message=None,
            updated_at=func.now(),
        )
    )
    db.commit()
    if not result.rowcount:
        raise_if_cancel_requested(db, job_id)
        raise JobClaimConflictError("任务已由其他 worker 领取")
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError("任务不存在")
    db.refresh(job)
    return job


def update_running_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    progress: int,
    message: str,
) -> Job:
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING.value,
            Job.run_token == run_token,
        )
        .values(
            progress=max(0, min(progress, 100)),
            message=_bounded_job_message(message),
            updated_at=func.now(),
        )
    )
    db.commit()
    return _get_transitioned_job(
        db,
        job_id,
        run_token,
        result.rowcount,
        "无法更新任务进度",
    )


def mark_job_cancelled(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    message: str,
) -> Job:
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.run_token == run_token,
            Job.status.in_(
                [JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLED.value]
            ),
        )
        .values(
            status=JobStatus.CANCELLED.value,
            run_token=None,
            message=_bounded_job_message(message),
            error_message=None,
            updated_at=func.now(),
        )
    )
    db.commit()
    return _get_transitioned_job(
        db,
        job_id,
        run_token,
        result.rowcount,
        "无法标记取消",
        allow_cleared_token=True,
    )


def complete_running_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    message: str,
) -> Job:
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING.value,
            Job.run_token == run_token,
        )
        .values(
            status=JobStatus.SUCCESS.value,
            run_token=None,
            progress=100,
            message=_bounded_job_message(message),
            error_message=None,
            updated_at=func.now(),
        )
    )
    db.commit()
    return _get_transitioned_job(
        db,
        job_id,
        run_token,
        result.rowcount,
        "无法标记完成",
        allow_cleared_token=True,
    )


def fail_active_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    message: str,
    error_message: str,
) -> Job:
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING.value,
            Job.run_token == run_token,
        )
        .values(
            status=JobStatus.FAILED.value,
            run_token=None,
            progress=100,
            message=_bounded_job_message(message),
            error_message=_bounded_job_error_message(error_message),
            updated_at=func.now(),
        )
    )
    db.commit()
    return _get_transitioned_job(
        db,
        job_id,
        run_token,
        result.rowcount,
        "无法标记失败",
        allow_cleared_token=True,
    )


def _get_transitioned_job(
    db: Session,
    job_id: UUID,
    run_token: UUID,
    rowcount: int | None,
    conflict_message: str,
    *,
    allow_cleared_token: bool = False,
) -> Job:
    if not rowcount:
        raise_if_job_stopped(db, job_id, run_token)
        raise JobConflictError(f"任务状态已变化，{conflict_message}")
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError("任务不存在")
    db.refresh(job)
    if not allow_cleared_token and job.run_token != run_token:
        raise JobClaimConflictError("任务执行权已转移给其他 worker")
    return job


def list_jobs(
    db: Session,
    user_id: UUID,
    *,
    page: int = 1,
    page_size: int = 20,
    status: JobStatus | None = None,
    job_type: JobType | None = None,
) -> tuple[list[JobView], int]:
    offset = offset_for_page(page, page_size)
    filters = [Job.user_id == user_id]
    if status is not None:
        filters.append(Job.status == status.value)
    if job_type is not None:
        filters.append(Job.job_type == job_type.value)

    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    rows = db.execute(
        _job_view_statement()
        .where(*filters)
        .order_by(
            Job.updated_at.desc(),
            Job.created_at.desc(),
            Job.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    )
    return [_job_view_from_row(row) for row in rows], total


def update_job(
    db: Session,
    job: Job,
    status: JobStatus | None = None,
    progress: int | None = None,
    message: str | None = None,
    error_message: str | None = None,
) -> Job:
    if status is not None:
        job.status = status.value
    if progress is not None:
        job.progress = max(0, min(progress, 100))
    if message is not None:
        job.message = _bounded_job_message(message)
    if error_message is not None:
        job.error_message = _bounded_job_error_message(error_message)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _job_view_statement():
    return select(
        Job.id,
        Job.user_id,
        Job.document_id,
        Job.retry_of_job_id,
        Job.job_type,
        Job.status,
        Job.progress,
        func.left(Job.message, JOB_MESSAGE_MAX_LENGTH).label("message"),
        func.left(
            Job.error_message,
            JOB_ERROR_MESSAGE_MAX_LENGTH,
        ).label("error_message"),
        Job.created_at,
        Job.updated_at,
    )


def _job_view_from_row(row) -> JobView:
    return JobView(*row)


def to_job_view(job: Job | JobView) -> JobView:
    if isinstance(job, JobView):
        return job
    return JobView(
        id=job.id,
        user_id=job.user_id,
        document_id=job.document_id,
        retry_of_job_id=job.retry_of_job_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        message=_bounded_job_message(job.message),
        error_message=_bounded_job_error_message(job.error_message),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _bounded_job_message(message: str | None) -> str | None:
    return message[:JOB_MESSAGE_MAX_LENGTH] if message is not None else None


def _bounded_job_error_message(message: str | None) -> str | None:
    return (
        message[:JOB_ERROR_MESSAGE_MAX_LENGTH]
        if message is not None
        else None
    )


def touch_running_job(job_id: UUID, run_token: UUID) -> bool:
    with SessionLocal() as db:
        result = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.run_token == run_token,
            )
            .values(updated_at=func.now())
        )
        db.commit()
        return bool(result.rowcount)


class JobHeartbeat:
    def __init__(
        self,
        job_id: UUID,
        run_token: UUID,
        interval_seconds: float | None = None,
    ) -> None:
        self._job_id = job_id
        self._run_token = run_token
        configured_interval = max(
            interval_seconds or settings.job_heartbeat_interval_seconds, 0.01
        )
        maximum_interval = max(
            settings.stale_job_after_minutes * 60 / 3,
            0.01,
        )
        self._interval_seconds = min(configured_interval, maximum_interval)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-heartbeat-{self._job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                if not touch_running_job(self._job_id, self._run_token):
                    return
            except Exception:
                logger.warning(
                    "Failed to update heartbeat for job %s",
                    self._job_id,
                    exc_info=True,
                )
