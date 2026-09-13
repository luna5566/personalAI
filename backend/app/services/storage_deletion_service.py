from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, set_local_statement_timeout
from app.models.document import Document
from app.models.storage_deletion import StorageDeletion
from app.storage import storage_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedStorageDeletion:
    id: UUID
    storage_backend: str
    storage_scope: str
    storage_key: str
    attempts: int
    lease_token: UUID


@dataclass(frozen=True)
class StorageDeletionBatchResult:
    claimed: int
    completed: int
    failed: int


@dataclass(frozen=True)
class StorageDeletionQueueSnapshot:
    pending: int
    failed: int
    abandoned: int
    active_leases: int
    eligible: int
    oldest_created_at: datetime | None
    earliest_next_attempt_at: datetime | None


@dataclass(frozen=True)
class StorageDeletionRetryInfo:
    status: str
    storage_backend: str
    storage_scope: str
    storage_key: str
    attempts: int | None = None
    last_error: str | None = None
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None

    @property
    def retryable(self) -> bool:
        return self.status in {
            "failed_backoff",
            "abandoned_backoff",
            "eligible",
        }

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "status": self.status,
            "retryable": self.retryable,
            "storage_backend": self.storage_backend,
            "storage_scope": self.storage_scope,
            "storage_key": self.storage_key,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "next_attempt_at": (
                self.next_attempt_at.isoformat()
                if self.next_attempt_at is not None
                else None
            ),
            "lease_expires_at": (
                self.lease_expires_at.isoformat()
                if self.lease_expires_at is not None
                else None
            ),
        }


def enqueue_storage_deletion(
    db: Session,
    storage_key: str | None,
    *,
    storage_backend: str | None = None,
    storage_scope: str | None = None,
) -> bool:
    if not storage_key:
        return False
    if (storage_backend is None) != (storage_scope is None):
        raise ValueError(
            "storage backend and scope must be provided together"
        )
    statement = (
        insert(StorageDeletion)
        .values(
            storage_backend=storage_backend or settings.storage_backend,
            storage_scope=(
                storage_scope or storage_service.current_storage_scope()
            ),
            storage_key=storage_key,
        )
        .on_conflict_do_nothing(
            constraint="uq_storage_deletions_location_key"
        )
        .returning(StorageDeletion.id)
    )
    result = db.execute(statement)
    return result.scalar_one_or_none() is not None


def enqueue_document_storage_deletions(
    db: Session,
    *,
    user_id: UUID,
) -> int:
    locations = (
        select(
            Document.storage_backend.label("storage_backend"),
            Document.storage_scope.label("storage_scope"),
            Document.file_path.label("storage_key"),
        )
        .where(
            Document.user_id == user_id,
            Document.file_path.is_not(None),
            Document.file_path != "",
        )
        .distinct()
        .subquery("document_storage_locations")
    )
    statement = (
        insert(StorageDeletion)
        .from_select(
            (
                "id",
                "storage_backend",
                "storage_scope",
                "storage_key",
                "attempts",
            ),
            select(
                func.gen_random_uuid(),
                locations.c.storage_backend,
                locations.c.storage_scope,
                locations.c.storage_key,
                literal(0),
            ),
            include_defaults=False,
        )
        .on_conflict_do_nothing(
            constraint="uq_storage_deletions_location_key"
        )
    )
    rowcount = db.execute(statement).rowcount
    return rowcount if rowcount is not None and rowcount > 0 else 0


def storage_deletion_queue_snapshot(
    db: Session,
) -> StorageDeletionQueueSnapshot:
    now = func.now()
    lease_available = or_(
        StorageDeletion.lease_expires_at.is_(None),
        StorageDeletion.lease_expires_at <= now,
    )
    row = db.execute(
        select(
            func.count(StorageDeletion.id),
            func.count(StorageDeletion.id).filter(
                StorageDeletion.last_error.is_not(None)
            ),
            func.count(StorageDeletion.id).filter(
                StorageDeletion.attempts > 0,
                StorageDeletion.last_error.is_(None),
                lease_available,
            ),
            func.count(StorageDeletion.id).filter(
                StorageDeletion.lease_token.is_not(None),
                StorageDeletion.lease_expires_at > now,
            ),
            func.count(StorageDeletion.id).filter(
                StorageDeletion.next_attempt_at <= now,
                lease_available,
            ),
            func.min(StorageDeletion.created_at),
            func.min(StorageDeletion.next_attempt_at),
        )
    ).one()
    return StorageDeletionQueueSnapshot(
        pending=int(row[0]),
        failed=int(row[1]),
        abandoned=int(row[2]),
        active_leases=int(row[3]),
        eligible=int(row[4]),
        oldest_created_at=row[5],
        earliest_next_attempt_at=row[6],
    )


def inspect_storage_deletion_retry(
    db: Session,
    storage_key: str,
) -> StorageDeletionRetryInfo:
    storage_backend = settings.storage_backend
    storage_scope = storage_service.current_storage_scope()
    try:
        storage_service.validate_key(storage_key)
    except ValueError:
        return StorageDeletionRetryInfo(
            status="invalid_key",
            storage_backend=storage_backend,
            storage_scope=storage_scope,
            storage_key=storage_key,
        )
    row = db.scalar(
        select(StorageDeletion).where(
            StorageDeletion.storage_backend == storage_backend,
            StorageDeletion.storage_scope == storage_scope,
            StorageDeletion.storage_key == storage_key,
        )
    )
    if row is None:
        return StorageDeletionRetryInfo(
            status="not_found",
            storage_backend=storage_backend,
            storage_scope=storage_scope,
            storage_key=storage_key,
        )
    return _storage_deletion_retry_info(row, _database_now(db))


def retry_storage_deletion_now(
    db: Session,
    storage_key: str,
) -> StorageDeletionRetryInfo:
    storage_backend = settings.storage_backend
    storage_scope = storage_service.current_storage_scope()
    try:
        storage_service.validate_key(storage_key)
    except ValueError:
        return StorageDeletionRetryInfo(
            status="invalid_key",
            storage_backend=storage_backend,
            storage_scope=storage_scope,
            storage_key=storage_key,
        )
    row = db.scalar(
        select(StorageDeletion)
        .where(
            StorageDeletion.storage_backend == storage_backend,
            StorageDeletion.storage_scope == storage_scope,
            StorageDeletion.storage_key == storage_key,
        )
        .with_for_update()
    )
    if row is None:
        return StorageDeletionRetryInfo(
            status="not_found",
            storage_backend=storage_backend,
            storage_scope=storage_scope,
            storage_key=storage_key,
        )

    now = _database_now(db)
    info = _storage_deletion_retry_info(row, now)
    if info.status not in {"failed_backoff", "abandoned_backoff"}:
        return info
    row.next_attempt_at = now
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now
    db.add(row)
    return StorageDeletionRetryInfo(
        status="scheduled",
        storage_backend=row.storage_backend,
        storage_scope=row.storage_scope,
        storage_key=row.storage_key,
        attempts=row.attempts,
        last_error=row.last_error,
        next_attempt_at=now,
        lease_expires_at=None,
    )


def claim_storage_deletions(
    limit: int | None = None,
) -> list[ClaimedStorageDeletion]:
    claim_limit = min(
        settings.storage_deletion_batch_size,
        max(limit, 0)
        if limit is not None
        else settings.storage_deletion_batch_size,
    )
    if claim_limit == 0:
        return []

    with SessionLocal() as db:
        set_local_statement_timeout(
            db,
            settings.storage_deletion_statement_timeout_seconds,
        )
        now = _database_now(db)
        rows = list(
            db.scalars(
                select(StorageDeletion)
                .where(
                    StorageDeletion.next_attempt_at <= now,
                    or_(
                        StorageDeletion.lease_expires_at.is_(None),
                        StorageDeletion.lease_expires_at <= now,
                    ),
                )
                .order_by(StorageDeletion.created_at, StorageDeletion.id)
                .limit(claim_limit)
                .with_for_update(skip_locked=True)
            )
        )

        claims: list[ClaimedStorageDeletion] = []
        lease_expires_at = now + timedelta(
            seconds=settings.storage_deletion_lease_seconds
        )
        for row in rows:
            lease_token = uuid4()
            row.attempts += 1
            row.lease_token = lease_token
            row.lease_expires_at = lease_expires_at
            row.updated_at = now
            db.add(row)
            claims.append(
                ClaimedStorageDeletion(
                    id=row.id,
                    storage_backend=row.storage_backend,
                    storage_scope=row.storage_scope,
                    storage_key=row.storage_key,
                    attempts=row.attempts,
                    lease_token=lease_token,
                )
            )
        db.commit()
        return claims


def complete_storage_deletion(claim: ClaimedStorageDeletion) -> bool:
    with SessionLocal() as db:
        set_local_statement_timeout(
            db,
            settings.storage_deletion_statement_timeout_seconds,
        )
        result = db.execute(
            delete(StorageDeletion).where(
                StorageDeletion.id == claim.id,
                StorageDeletion.lease_token == claim.lease_token,
            )
        )
        db.commit()
        return result.rowcount == 1


def fail_storage_deletion(
    claim: ClaimedStorageDeletion,
    error: Exception,
) -> bool:
    with SessionLocal() as db:
        set_local_statement_timeout(
            db,
            settings.storage_deletion_statement_timeout_seconds,
        )
        now = _database_now(db)
        next_attempt_at = now + timedelta(
            seconds=storage_deletion_retry_delay_seconds(claim.attempts)
        )
        result = db.execute(
            update(StorageDeletion)
            .where(
                StorageDeletion.id == claim.id,
                StorageDeletion.lease_token == claim.lease_token,
            )
            .values(
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=next_attempt_at,
                last_error=type(error).__name__[:255],
                updated_at=now,
            )
        )
        db.commit()
        return result.rowcount == 1


def process_storage_deletion_batch(
    limit: int | None = None,
) -> StorageDeletionBatchResult:
    claims = claim_storage_deletions(limit=limit)
    completed = 0
    failed = 0
    for claim in claims:
        try:
            storage_service.delete_key_for_backend(
                claim.storage_key,
                claim.storage_backend,
                claim.storage_scope,
            )
        except Exception as error:
            failed += 1
            try:
                fail_storage_deletion(claim, error)
            except Exception:
                logger.warning(
                    "Failed to release a storage deletion lease",
                    exc_info=True,
                )
            logger.warning(
                "Queued storage deletion failed and will be retried",
                exc_info=True,
            )
            continue

        if complete_storage_deletion(claim):
            completed += 1

    return StorageDeletionBatchResult(
        claimed=len(claims),
        completed=completed,
        failed=failed,
    )


def storage_deletion_retry_delay_seconds(attempts: int) -> int:
    exponent = min(max(attempts - 1, 0), 30)
    return min(
        settings.storage_deletion_retry_base_seconds * (2**exponent),
        settings.storage_deletion_retry_max_seconds,
    )


def _database_now(db: Session) -> datetime:
    now = db.scalar(select(func.now()))
    if not isinstance(now, datetime):
        raise RuntimeError("database did not return a timestamp")
    return now


def _storage_deletion_retry_info(
    row: StorageDeletion,
    now: datetime,
) -> StorageDeletionRetryInfo:
    lease_is_incomplete = (row.lease_token is None) != (
        row.lease_expires_at is None
    )
    if lease_is_incomplete:
        status = "invalid_lease"
    elif (
        row.lease_token is not None
        and row.lease_expires_at is not None
        and row.lease_expires_at > now
    ):
        status = "active_lease"
    elif row.attempts <= 0:
        status = "not_attempted"
    elif row.next_attempt_at <= now:
        status = "eligible"
    elif row.last_error:
        status = "failed_backoff"
    else:
        status = "abandoned_backoff"
    return StorageDeletionRetryInfo(
        status=status,
        storage_backend=row.storage_backend,
        storage_scope=row.storage_scope,
        storage_key=row.storage_key,
        attempts=row.attempts,
        last_error=row.last_error,
        next_attempt_at=row.next_attempt_at,
        lease_expires_at=row.lease_expires_at,
    )
