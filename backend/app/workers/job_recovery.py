from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text

from app.core.config import settings
from app.core.database import SessionLocal, set_local_statement_timeout
from app.core.observability import job_queue_depth
from app.models.document import Document, DocumentStatus
from app.models.job import Job, JobStatus, JobType
from app.services import (
    embedding_configuration_service,
    job_service,
    maintenance_service,
)
from app.workers.document_pipeline import process_document, rebuild_embeddings
from app.workers.job_execution import JobWorkerLimiter, job_worker_limiter

logger = logging.getLogger(__name__)
RECOVERABLE_JOB_STATUS_PREDICATE = text(
    "jobs.status IN ('pending', 'cancel_requested', 'running')"
)
JOB_STATUS_VALUES = tuple(status.value for status in JobStatus)


def update_job_queue_depth(db) -> None:
    """把按状态分组的任务计数写入 Prometheus gauge。"""
    rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    counts = {status: 0 for status in JOB_STATUS_VALUES}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    for status, count in counts.items():
        job_queue_depth.labels(status=status).set(count)


def record_job_queue_depth() -> None:
    """周期采集任务队列深度；失败只记录日志，不影响恢复调度。"""
    if not settings.metrics_enabled:
        return
    try:
        with SessionLocal() as db:
            set_local_statement_timeout(
                db,
                settings.job_recovery_statement_timeout_seconds,
            )
            update_job_queue_depth(db)
    except Exception:
        logger.debug("Recording job queue depth failed", exc_info=True)


@dataclass(frozen=True)
class RecoverableJob:
    id: UUID
    user_id: UUID
    document_id: UUID | None
    job_type: str
    run_token: UUID


@dataclass(frozen=True)
class JobRecoverySnapshot:
    last_scan_at: datetime | None
    last_success_at: datetime | None
    scan_started_at: datetime | None
    last_scan_duration_ms: int | None
    consecutive_failures: int
    last_dispatched_jobs: int
    active_workers: int


class JobRecoveryState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_scan_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._scan_started_at: datetime | None = None
        self._scan_started_monotonic: float | None = None
        self._last_scan_duration_ms: int | None = None
        self._consecutive_failures = 0
        self._last_dispatched_jobs = 0
        self._active_workers = 0

    def record_scan_started(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._scan_started_at = now
            self._scan_started_monotonic = monotonic()

    def record_success(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._finish_scan()
            self._last_scan_at = now
            self._last_success_at = now
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._finish_scan()
            self._last_scan_at = now
            self._consecutive_failures += 1

    def record_scan_cancelled(self) -> None:
        with self._lock:
            self._scan_started_at = None
            self._scan_started_monotonic = None

    def _finish_scan(self) -> None:
        if self._scan_started_monotonic is not None:
            elapsed_ms = round(
                (monotonic() - self._scan_started_monotonic) * 1000
            )
            self._last_scan_duration_ms = max(elapsed_ms, 0)
        self._scan_started_at = None
        self._scan_started_monotonic = None

    def reserve_worker_slots(self, requested: int, max_workers: int) -> int:
        with self._lock:
            available = max(max_workers - self._active_workers, 0)
            reserved = min(max(requested, 0), available)
            self._active_workers += reserved
            return reserved

    def record_dispatched_jobs(self, count: int, reserved_slots: int) -> None:
        dispatched = max(count, 0)
        reserved = max(reserved_slots, 0)
        with self._lock:
            self._last_dispatched_jobs = dispatched
            self._active_workers = max(
                self._active_workers - max(reserved - dispatched, 0),
                0,
            )

    def release_worker_slots(self, count: int) -> None:
        with self._lock:
            self._active_workers = max(
                self._active_workers - max(count, 0),
                0,
            )

    def record_worker_finished(self) -> None:
        with self._lock:
            self._active_workers = max(self._active_workers - 1, 0)

    def snapshot(self) -> JobRecoverySnapshot:
        with self._lock:
            return JobRecoverySnapshot(
                last_scan_at=self._last_scan_at,
                last_success_at=self._last_success_at,
                scan_started_at=self._scan_started_at,
                last_scan_duration_ms=self._last_scan_duration_ms,
                consecutive_failures=self._consecutive_failures,
                last_dispatched_jobs=self._last_dispatched_jobs,
                active_workers=self._active_workers,
            )


class JobRecoveryTaskRegistry:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_for_completion(self, timeout_seconds: float) -> bool:
        tasks = set(self._tasks)
        if not tasks:
            return True

        _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        if not pending:
            return True

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return False


def claim_recoverable_jobs(limit: int | None = None) -> list[RecoverableJob]:
    claim_limit = min(
        settings.job_recovery_batch_size,
        max(limit, 0) if limit is not None else settings.job_recovery_batch_size,
    )
    if claim_limit == 0:
        return []
    stale_before = datetime.now(UTC) - timedelta(minutes=settings.stale_job_after_minutes)
    with SessionLocal() as db:
        set_local_statement_timeout(
            db,
            settings.job_recovery_statement_timeout_seconds,
        )
        embedding_configuration_service.reconcile_embedding_configuration(
            db,
            settings.runtime_settings_admin_user_id,
        )
        set_local_statement_timeout(
            db,
            settings.job_recovery_statement_timeout_seconds,
        )
        job_service.add_missing_document_jobs(db, claim_limit)
        jobs = list(
            db.scalars(
                select(Job)
                .where(
                    RECOVERABLE_JOB_STATUS_PREDICATE,
                    or_(
                        Job.status == JobStatus.PENDING.value,
                        Job.status == JobStatus.CANCEL_REQUESTED.value,
                        and_(
                            Job.status == JobStatus.RUNNING.value,
                            Job.updated_at < stale_before,
                        ),
                    )
                )
                .order_by(Job.created_at, Job.id)
                .limit(claim_limit)
                .with_for_update(skip_locked=True)
            )
        )
        claimed = []
        for job in jobs:
            if job.status == JobStatus.CANCEL_REQUESTED.value:
                job.status = JobStatus.CANCELLED.value
                job.run_token = None
                job.message = "服务恢复时完成取消"
                job.error_message = None
                if job.job_type == JobType.INDEX_DOCUMENT.value and job.document_id is not None:
                    document = db.get(Document, job.document_id)
                    if document is not None and document.status != DocumentStatus.INDEXED.value:
                        document.status = DocumentStatus.CANCELLED.value
                        document.error_message = None
                        db.add(document)
                db.add(job)
                continue
            run_token = uuid4()
            job.status = JobStatus.RUNNING.value
            job.run_token = run_token
            job.message = "服务恢复后继续处理"
            job.error_message = None
            db.add(job)
            claimed.append(
                RecoverableJob(
                    id=job.id,
                    user_id=job.user_id,
                    document_id=job.document_id,
                    job_type=job.job_type,
                    run_token=run_token,
                )
            )
        db.commit()
        return claimed


async def _claim_recoverable_jobs_without_orphaning(
    limit: int,
) -> tuple[list[RecoverableJob], bool]:
    claim_task = asyncio.create_task(
        asyncio.to_thread(claim_recoverable_jobs, limit=limit)
    )
    cancellation_requested = False
    while not claim_task.done():
        try:
            await asyncio.shield(claim_task)
        except asyncio.CancelledError:
            cancellation_requested = True

    try:
        jobs = claim_task.result()
    except Exception:
        if cancellation_requested:
            logger.warning(
                "Recovery scan failed while the supervisor was stopping",
                exc_info=True,
            )
            raise asyncio.CancelledError() from None
        raise
    return jobs, cancellation_requested


async def schedule_recoverable_jobs(
    *,
    run_maintenance: bool = True,
    state: JobRecoveryState | None = None,
    task_registry: JobRecoveryTaskRegistry | None = None,
    worker_limiter: JobWorkerLimiter | None = None,
) -> list[asyncio.Task[None]]:
    if run_maintenance:
        await asyncio.to_thread(maintenance_service.purge_expired_data)
    record_job_queue_depth()

    reserved_slots = settings.job_recovery_batch_size
    if state is not None:
        reserved_slots = state.reserve_worker_slots(
            settings.job_recovery_batch_size,
            settings.job_recovery_max_active_workers,
        )
        if reserved_slots == 0:
            state.record_dispatched_jobs(0, 0)
            return []

    limiter = worker_limiter or job_worker_limiter
    permits = limiter.reserve_up_to(reserved_slots)
    admitted_slots = len(permits)
    if state is not None and admitted_slots < reserved_slots:
        state.release_worker_slots(reserved_slots - admitted_slots)
    reserved_slots = admitted_slots
    if reserved_slots == 0:
        if state is not None:
            state.record_dispatched_jobs(0, 0)
        return []

    tasks: list[asyncio.Task[None]] = []
    cancellation_requested = False
    try:
        jobs, cancellation_requested = (
            await _claim_recoverable_jobs_without_orphaning(reserved_slots)
        )
        for job, permit in zip(jobs, permits):
            task = asyncio.create_task(permit.run(run_recoverable_job, job))
            task.add_done_callback(
                lambda completed, recovery_state=state: _consume_task_result(
                    completed,
                    recovery_state,
                )
            )
            if task_registry is not None:
                task_registry.track(task)
            tasks.append(task)
    except BaseException:
        for permit in permits[len(tasks) :]:
            permit.release()
        if state is not None:
            state.record_dispatched_jobs(len(tasks), reserved_slots)
        raise

    for permit in permits[len(tasks) :]:
        permit.release()
    if state is not None:
        state.record_dispatched_jobs(len(tasks), reserved_slots)
    if cancellation_requested:
        raise asyncio.CancelledError()
    return tasks


async def run_recovery_loop(
    state: JobRecoveryState | None = None,
    task_registry: JobRecoveryTaskRegistry | None = None,
) -> None:
    recovery_state = state or JobRecoveryState()
    while True:
        await asyncio.sleep(settings.job_recovery_interval_seconds)
        recovery_state.record_scan_started()
        try:
            await schedule_recoverable_jobs(
                run_maintenance=True,
                state=recovery_state,
                task_registry=task_registry,
            )
        except asyncio.CancelledError:
            recovery_state.record_scan_cancelled()
            raise
        except Exception:
            recovery_state.record_failure()
            logger.warning("Periodic job recovery scan failed", exc_info=True)
        else:
            recovery_state.record_success()


def run_recoverable_job(job: RecoverableJob) -> None:
    if job.job_type == JobType.INDEX_DOCUMENT.value and job.document_id is not None:
        process_document(job.id, job.document_id, run_token=job.run_token)
        return
    if job.job_type == JobType.REBUILD_EMBEDDINGS.value:
        rebuild_embeddings(job.id, job.user_id, run_token=job.run_token)
        return
    if job.job_type == JobType.REBUILD_ALL_EMBEDDINGS.value:
        rebuild_embeddings(job.id, None, run_token=job.run_token)
        return

    logger.warning(
        "Cannot recover unsupported job type",
        extra={"job_id": str(job.id), "job_type": job.job_type},
    )
    with SessionLocal() as db:
        stored_job = db.get(Job, job.id)
        if stored_job is not None:
            try:
                job_service.fail_active_job(
                    db,
                    job.id,
                    job.run_token,
                    message="无法恢复未知任务",
                    error_message="任务类型不受支持，无法自动恢复",
                )
            except job_service.JobCancelledError:
                job_service.mark_job_cancelled(
                    db,
                    job.id,
                    job.run_token,
                    "任务已取消",
                )


def _consume_task_result(
    task: asyncio.Task[None],
    state: JobRecoveryState | None = None,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Recovered job worker failed", exc_info=True)
    finally:
        if state is not None:
            state.record_worker_finished()
