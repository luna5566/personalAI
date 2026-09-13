from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, set_local_statement_timeout
from app.models.auth_login_attempt import AuthLoginAttempt
from app.models.auth_session import AuthSession
from app.models.job import Job, JobStatus

TERMINAL_JOB_STATUSES = (
    JobStatus.SUCCESS.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
)


@dataclass(frozen=True)
class MaintenanceCleanupResult:
    auth_sessions: int
    auth_login_attempts: int
    jobs: int


def purge_expired_data(
    batch_size: int | None = None,
) -> MaintenanceCleanupResult:
    limit = (
        settings.maintenance_cleanup_batch_size
        if batch_size is None
        else batch_size
    )
    if limit <= 0:
        return MaintenanceCleanupResult(0, 0, 0)

    with SessionLocal() as db:
        set_local_statement_timeout(
            db,
            settings.job_recovery_statement_timeout_seconds,
        )
        now = db.scalar(select(func.now()))
        if not isinstance(now, datetime):
            raise RuntimeError("database did not return a timestamp")
        attempt_retention_seconds = max(
            settings.auth_login_attempt_retention_seconds,
            settings.auth_registration_attempt_retention_seconds,
        )
        result = MaintenanceCleanupResult(
            auth_sessions=_delete_batch(
                db,
                model=AuthSession,
                key_column=AuthSession.id,
                predicate=AuthSession.expires_at <= now,
                order_by=(AuthSession.expires_at, AuthSession.id),
                limit=limit,
                cte_name="expired_auth_sessions",
            ),
            auth_login_attempts=_delete_batch(
                db,
                model=AuthLoginAttempt,
                key_column=AuthLoginAttempt.scope_hash,
                predicate=(
                    AuthLoginAttempt.updated_at
                    < now - timedelta(seconds=attempt_retention_seconds)
                ),
                order_by=(
                    AuthLoginAttempt.updated_at,
                    AuthLoginAttempt.scope_hash,
                ),
                limit=limit,
                cte_name="expired_auth_login_attempts",
            ),
            jobs=_delete_batch(
                db,
                model=Job,
                key_column=Job.id,
                predicate=(
                    Job.status.in_(TERMINAL_JOB_STATUSES)
                    & (
                        Job.updated_at
                        < now - timedelta(days=settings.job_retention_days)
                    )
                ),
                order_by=(Job.updated_at, Job.id),
                limit=limit,
                cte_name="expired_jobs",
            ),
        )
        db.commit()
        return result


def _delete_batch(
    db: Session,
    *,
    model,
    key_column,
    predicate,
    order_by: tuple,
    limit: int,
    cte_name: str,
) -> int:
    candidates = (
        select(key_column.label("candidate_key"))
        .where(predicate)
        .order_by(*order_by)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .cte(cte_name)
    )
    result = db.execute(
        delete(model).where(
            key_column.in_(select(candidates.c.candidate_key))
        )
    )
    return int(result.rowcount or 0)
