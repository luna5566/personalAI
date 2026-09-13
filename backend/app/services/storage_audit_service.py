from __future__ import annotations

import sqlite3
from bisect import bisect_left
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.storage_deletion import StorageDeletion
from app.services import storage_deletion_service
from app.storage import storage_service

_EXPECTED_KEY_UPSERT_SQL = """
    INSERT INTO expected_keys (storage_key, referenced, pending_deletion)
    VALUES (?, ?, ?)
    ON CONFLICT(storage_key) DO UPDATE SET
        referenced = MAX(referenced, excluded.referenced),
        pending_deletion = MAX(pending_deletion, excluded.pending_deletion)
"""


class StorageObjectNotOrphanError(ValueError):
    pass


@dataclass(frozen=True)
class OrphanInspection:
    storage_backend: str
    storage_scope: str
    storage_key: str
    is_orphan: bool

    def as_dict(self) -> dict[str, str]:
        return {
            "status": "orphan" if self.is_orphan else "not_orphan",
            "storage_backend": self.storage_backend,
            "storage_scope": self.storage_scope,
            "storage_key": self.storage_key,
        }


@dataclass(frozen=True)
class OrphanDeletionReceipt:
    storage_backend: str
    storage_scope: str
    storage_key: str
    created: bool

    def as_dict(self) -> dict[str, str]:
        return {
            "status": "queued" if self.created else "already_queued",
            "storage_backend": self.storage_backend,
            "storage_scope": self.storage_scope,
            "storage_key": self.storage_key,
        }


@dataclass(frozen=True)
class StorageAuditResult:
    storage_backend: str
    storage_scope: str
    managed_prefix: str
    sample_limit: int
    referenced_count: int
    pending_deletion_count: int
    inventory_count: int
    missing_document_count: int
    orphan_count: int
    invalid_document_count: int
    invalid_pending_deletion_count: int
    missing_document_keys: tuple[str, ...]
    orphan_keys: tuple[str, ...]
    invalid_document_keys: tuple[str, ...]
    invalid_pending_deletion_keys: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        return not any(
            (
                self.missing_document_count,
                self.orphan_count,
                self.invalid_document_count,
                self.invalid_pending_deletion_count,
            )
        )

    @property
    def exit_code(self) -> int:
        return 0 if self.is_consistent else 1

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "consistent" if self.is_consistent else "drift",
            "storage_backend": self.storage_backend,
            "storage_scope": self.storage_scope,
            "managed_prefix": self.managed_prefix,
            "sample_limit": self.sample_limit,
            "counts": {
                "referenced": self.referenced_count,
                "pending_deletion": self.pending_deletion_count,
                "inventory": self.inventory_count,
                "missing_documents": self.missing_document_count,
                "orphans": self.orphan_count,
                "invalid_documents": self.invalid_document_count,
                "invalid_pending_deletions": (
                    self.invalid_pending_deletion_count
                ),
            },
            "missing_document_keys": list(self.missing_document_keys),
            "orphan_keys": list(self.orphan_keys),
            "invalid_document_keys": list(self.invalid_document_keys),
            "invalid_pending_deletion_keys": list(
                self.invalid_pending_deletion_keys
            ),
            "diagnostics_truncated": {
                "missing_document_keys": (
                    self.missing_document_count
                    > len(self.missing_document_keys)
                ),
                "orphan_keys": self.orphan_count > len(self.orphan_keys),
                "invalid_document_keys": (
                    self.invalid_document_count
                    > len(self.invalid_document_keys)
                ),
                "invalid_pending_deletion_keys": (
                    self.invalid_pending_deletion_count
                    > len(self.invalid_pending_deletion_keys)
                ),
            },
        }


class _BoundedKeySamples:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0
        self.keys: list[str] = []

    def add(self, key: str) -> None:
        self.count += 1
        if self.limit == 0:
            return
        position = bisect_left(self.keys, key)
        if position < len(self.keys) and self.keys[position] == key:
            return
        if len(self.keys) < self.limit:
            self.keys.insert(position, key)
            return
        if position < self.limit:
            self.keys.insert(position, key)
            self.keys.pop()


def audit_current_storage(
    db: Session,
    *,
    batch_size: int | None = None,
    sample_limit: int | None = None,
) -> StorageAuditResult:
    batch_size = (
        settings.storage_audit_batch_size
        if batch_size is None
        else batch_size
    )
    sample_limit = (
        settings.storage_audit_sample_limit
        if sample_limit is None
        else sample_limit
    )
    _validate_audit_limits(batch_size, sample_limit)
    storage_backend = settings.storage_backend
    storage_scope = storage_service.current_storage_scope()
    managed_prefix = storage_service.managed_key_prefix()

    with TemporaryDirectory(prefix="personal-ai-storage-audit-") as directory:
        index_path = Path(directory) / "expected-keys.sqlite3"
        with closing(sqlite3.connect(index_path)) as key_index:
            _initialize_key_index(key_index)
            _load_expected_keys(
                db,
                key_index,
                storage_backend=storage_backend,
                storage_scope=storage_scope,
                batch_size=batch_size,
            )
            result = _audit_indexed_keys(
                key_index,
                storage_backend=storage_backend,
                storage_scope=storage_scope,
                managed_prefix=managed_prefix,
                sample_limit=sample_limit,
            )
    return result


def inspect_orphan_status(
    db: Session,
    storage_key: str,
) -> OrphanInspection:
    storage_backend = settings.storage_backend
    storage_scope = storage_service.current_storage_scope()
    managed_prefix = storage_service.managed_key_prefix()
    is_orphan = False
    if _is_managed_key(storage_key, managed_prefix):
        try:
            storage_service.validate_key(storage_key)
        except ValueError:
            pass
        else:
            if storage_service.key_exists(storage_key):
                is_orphan = not _is_expected_storage_key(
                    db,
                    storage_key,
                    storage_backend=storage_backend,
                    storage_scope=storage_scope,
                )
    return OrphanInspection(
        storage_backend=storage_backend,
        storage_scope=storage_scope,
        storage_key=storage_key,
        is_orphan=is_orphan,
    )


def enqueue_orphan_deletion(
    db: Session,
    storage_key: str,
) -> OrphanDeletionReceipt:
    inspection = inspect_orphan_status(db, storage_key)
    if not inspection.is_orphan:
        raise StorageObjectNotOrphanError(
            "对象不是当前存储审计中的孤立对象"
        )
    created = storage_deletion_service.enqueue_storage_deletion(
        db,
        storage_key,
        storage_backend=inspection.storage_backend,
        storage_scope=inspection.storage_scope,
    )
    db.commit()
    return OrphanDeletionReceipt(
        storage_backend=inspection.storage_backend,
        storage_scope=inspection.storage_scope,
        storage_key=storage_key,
        created=created,
    )


def _initialize_key_index(key_index: sqlite3.Connection) -> None:
    key_index.execute("PRAGMA journal_mode=OFF")
    key_index.execute("PRAGMA synchronous=OFF")
    key_index.execute("PRAGMA temp_store=FILE")
    key_index.execute("PRAGMA cache_size=-2048")
    key_index.execute(
        """
        CREATE TABLE expected_keys (
            storage_key TEXT PRIMARY KEY,
            referenced INTEGER NOT NULL DEFAULT 0,
            pending_deletion INTEGER NOT NULL DEFAULT 0
        ) WITHOUT ROWID
        """
    )


def _load_expected_keys(
    db: Session,
    key_index: sqlite3.Connection,
    *,
    storage_backend: str,
    storage_scope: str,
    batch_size: int,
) -> None:
    for keys in _document_key_batches(
        db,
        storage_backend=storage_backend,
        storage_scope=storage_scope,
        batch_size=batch_size,
    ):
        key_index.executemany(
            _EXPECTED_KEY_UPSERT_SQL,
            ((key, 1, 0) for key in keys),
        )
        key_index.commit()
    for keys in _pending_deletion_key_batches(
        db,
        storage_backend=storage_backend,
        storage_scope=storage_scope,
        batch_size=batch_size,
    ):
        key_index.executemany(
            _EXPECTED_KEY_UPSERT_SQL,
            ((key, 0, 1) for key in keys),
        )
        key_index.commit()


def _document_key_batches(
    db: Session,
    *,
    storage_backend: str,
    storage_scope: str,
    batch_size: int,
):
    cursor: UUID | None = None
    while True:
        statement = select(Document.id, Document.file_path).where(
            Document.file_path.is_not(None),
            Document.storage_backend == storage_backend,
            Document.storage_scope == storage_scope,
        )
        if cursor is not None:
            statement = statement.where(Document.id > cursor)
        statement = statement.order_by(Document.id).limit(batch_size)
        try:
            rows = list(db.execute(statement).all())
        finally:
            db.rollback()
        if not rows:
            return
        cursor = rows[-1][0]
        yield tuple(row[1] for row in rows if row[1])


def _pending_deletion_key_batches(
    db: Session,
    *,
    storage_backend: str,
    storage_scope: str,
    batch_size: int,
):
    cursor: UUID | None = None
    while True:
        statement = select(
            StorageDeletion.id,
            StorageDeletion.storage_key,
        ).where(
            StorageDeletion.storage_backend == storage_backend,
            StorageDeletion.storage_scope == storage_scope,
        )
        if cursor is not None:
            statement = statement.where(StorageDeletion.id > cursor)
        statement = statement.order_by(StorageDeletion.id).limit(batch_size)
        try:
            rows = list(db.execute(statement).all())
        finally:
            db.rollback()
        if not rows:
            return
        cursor = rows[-1][0]
        yield tuple(row[1] for row in rows if row[1])


def _audit_indexed_keys(
    key_index: sqlite3.Connection,
    *,
    storage_backend: str,
    storage_scope: str,
    managed_prefix: str,
    sample_limit: int,
) -> StorageAuditResult:
    missing_documents = _BoundedKeySamples(sample_limit)
    invalid_documents = _BoundedKeySamples(sample_limit)
    for (key,) in key_index.execute(
        "SELECT storage_key FROM expected_keys "
        "WHERE referenced = 1 ORDER BY storage_key"
    ):
        try:
            storage_service.validate_key(key)
            exists = storage_service.key_exists(key)
        except ValueError:
            invalid_documents.add(key)
            continue
        if not exists:
            missing_documents.add(key)

    invalid_pending = _BoundedKeySamples(sample_limit)
    for (key,) in key_index.execute(
        "SELECT storage_key FROM expected_keys "
        "WHERE pending_deletion = 1 ORDER BY storage_key"
    ):
        try:
            storage_service.validate_key(key)
        except ValueError:
            invalid_pending.add(key)

    orphans = _BoundedKeySamples(sample_limit)
    inventory_count = 0
    for key in storage_service.iter_keys(managed_prefix or None):
        inventory_count += 1
        expected = key_index.execute(
            "SELECT 1 FROM expected_keys WHERE storage_key = ?",
            (key,),
        ).fetchone()
        if expected is None:
            orphans.add(key)

    return StorageAuditResult(
        storage_backend=storage_backend,
        storage_scope=storage_scope,
        managed_prefix=managed_prefix,
        sample_limit=sample_limit,
        referenced_count=_indexed_key_count(key_index, "referenced"),
        pending_deletion_count=_indexed_key_count(
            key_index,
            "pending_deletion",
        ),
        inventory_count=inventory_count,
        missing_document_count=missing_documents.count,
        orphan_count=orphans.count,
        invalid_document_count=invalid_documents.count,
        invalid_pending_deletion_count=invalid_pending.count,
        missing_document_keys=tuple(missing_documents.keys),
        orphan_keys=tuple(orphans.keys),
        invalid_document_keys=tuple(invalid_documents.keys),
        invalid_pending_deletion_keys=tuple(invalid_pending.keys),
    )


def _indexed_key_count(
    key_index: sqlite3.Connection,
    column: str,
) -> int:
    if column not in {"referenced", "pending_deletion"}:
        raise ValueError("Unsupported storage audit count column")
    row = key_index.execute(
        f"SELECT COUNT(*) FROM expected_keys WHERE {column} = 1"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _is_expected_storage_key(
    db: Session,
    storage_key: str,
    *,
    storage_backend: str,
    storage_scope: str,
) -> bool:
    document_exists = (
        select(Document.id)
        .where(
            Document.file_path.is_not(None),
            func.md5(Document.file_path) == func.md5(storage_key),
            Document.file_path == storage_key,
            Document.storage_backend == storage_backend,
            Document.storage_scope == storage_scope,
        )
        .exists()
    )
    deletion_exists = (
        select(StorageDeletion.id)
        .where(
            StorageDeletion.storage_key == storage_key,
            StorageDeletion.storage_backend == storage_backend,
            StorageDeletion.storage_scope == storage_scope,
        )
        .exists()
    )
    return bool(db.scalar(select(or_(document_exists, deletion_exists))))


def _is_managed_key(storage_key: str, managed_prefix: str) -> bool:
    normalized_prefix = managed_prefix.strip("/")
    if not normalized_prefix:
        return bool(storage_key)
    return storage_key.startswith(f"{normalized_prefix}/")


def _validate_audit_limits(batch_size: int, sample_limit: int) -> None:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Storage audit batch size must be a positive integer")
    if type(sample_limit) is not int or sample_limit < 0:
        raise ValueError("Storage audit sample limit cannot be negative")
