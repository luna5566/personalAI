from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.models.storage_deletion import StorageDeletion
from app.services import storage_deletion_service
from app.storage import storage_service


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _ClaimSession:
    def __init__(self, now, rows):
        self.now = now
        self.rows = rows
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def scalar(self, statement):
        return self.now

    def scalars(self, statement):
        return _ScalarRows(self.rows)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class _InsertSession:
    def __init__(self, inserted=True) -> None:
        self.inserted = inserted
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        value = uuid4() if self.inserted else None
        return type(
            "Result",
            (),
            {"scalar_one_or_none": lambda self: value},
        )()


class _RetrySession:
    def __init__(self, row, now) -> None:
        self.values = iter((row, now))
        self.statements = []
        self.added = []

    def scalar(self, statement):
        self.statements.append(statement)
        return next(self.values)

    def add(self, value):
        self.added.append(value)


def test_enqueue_storage_deletion_uses_current_backend(monkeypatch) -> None:
    session = _InsertSession()
    monkeypatch.setattr(storage_deletion_service.settings, "storage_backend", "s3")
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "current_storage_scope",
        lambda: '{"bucket":"example"}',
    )

    created = storage_deletion_service.enqueue_storage_deletion(
        session,
        "documents/example.pdf",
    )

    assert created is True
    assert len(session.statements) == 1
    compiled = session.statements[0].compile(
        dialect=postgresql.dialect()
    )
    assert compiled.params["storage_backend"] == "s3"
    assert compiled.params["storage_scope"] == '{"bucket":"example"}'
    assert compiled.params["storage_key"] == "documents/example.pdf"
    assert "ON CONFLICT ON CONSTRAINT uq_storage_deletions_location_key" in str(
        compiled
    )


def test_enqueue_storage_deletion_ignores_empty_key() -> None:
    session = _InsertSession()

    created = storage_deletion_service.enqueue_storage_deletion(session, None)

    assert created is False
    assert session.statements == []


def test_enqueue_storage_deletion_preserves_document_storage_scope() -> None:
    session = _InsertSession()

    created = storage_deletion_service.enqueue_storage_deletion(
        session,
        "documents/example.pdf",
        storage_backend="s3",
        storage_scope='{"bucket":"original"}',
    )

    compiled = session.statements[0].compile(
        dialect=postgresql.dialect()
    )
    assert created is True
    assert compiled.params["storage_backend"] == "s3"
    assert compiled.params["storage_scope"] == '{"bucket":"original"}'


def test_enqueue_storage_deletion_reports_existing_intent() -> None:
    session = _InsertSession(inserted=False)

    created = storage_deletion_service.enqueue_storage_deletion(
        session,
        "documents/example.pdf",
        storage_backend="local",
        storage_scope="scope",
    )

    assert created is False
    assert len(session.statements) == 1


def test_storage_deletion_location_is_unique() -> None:
    names = {
        constraint.name
        for constraint in StorageDeletion.__table__.constraints
    }

    assert "uq_storage_deletions_location_key" in names


def test_storage_deletion_queue_snapshot_aggregates_persistent_state() -> None:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    next_attempt = now + timedelta(minutes=5)
    statements = []

    class QueueSession:
        def execute(self, statement):
            statements.append(statement)
            return type(
                "Result",
                (),
                {
                    "one": lambda self: (
                        5,
                        2,
                        1,
                        1,
                        3,
                        now,
                        next_attempt,
                    )
                },
            )()

    snapshot = storage_deletion_service.storage_deletion_queue_snapshot(
        QueueSession()
    )

    assert snapshot == storage_deletion_service.StorageDeletionQueueSnapshot(
        pending=5,
        failed=2,
        abandoned=1,
        active_leases=1,
        eligible=3,
        oldest_created_at=now,
        earliest_next_attempt_at=next_attempt,
    )
    sql = str(statements[0])
    assert "storage_deletions.last_error IS NOT NULL" in sql
    assert "storage_deletions.attempts >" in sql
    assert "storage_deletions.lease_expires_at" in sql


def _retry_row(
    now,
    *,
    attempts=1,
    last_error="StorageBackendChangedError",
    next_attempt_at=None,
    lease_token=None,
    lease_expires_at=None,
):
    return StorageDeletion(
        id=uuid4(),
        storage_backend="local",
        storage_scope="scope",
        storage_key="documents/example.txt",
        attempts=attempts,
        last_error=last_error,
        next_attempt_at=next_attempt_at or now + timedelta(minutes=30),
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
    )


@pytest.mark.parametrize(
    "last_error",
    ["StorageBackendChangedError", None],
)
def test_backoff_storage_deletion_is_scheduled_at_database_now(
    monkeypatch,
    last_error,
) -> None:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    expired_token = uuid4()
    row = _retry_row(
        now,
        last_error=last_error,
        lease_token=expired_token,
        lease_expires_at=now - timedelta(seconds=1),
    )
    session = _RetrySession(row, now)
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_backend",
        "local",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "current_storage_scope",
        lambda: "scope",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "validate_key",
        lambda key: None,
    )

    result = storage_deletion_service.retry_storage_deletion_now(
        session,
        row.storage_key,
    )

    assert result.status == "scheduled"
    assert result.retryable is False
    assert row.next_attempt_at == now
    assert row.lease_token is None
    assert row.lease_expires_at is None
    assert session.added == [row]
    assert "FOR UPDATE" in str(session.statements[0])


@pytest.mark.parametrize(
    ("row_kwargs", "expected_status", "retryable"),
    [
        (
            {
                "last_error": None,
                "next_attempt_at": datetime(2026, 7, 18, tzinfo=timezone.utc)
                + timedelta(minutes=30),
            },
            "abandoned_backoff",
            True,
        ),
        (
            {
                "lease_token": uuid4(),
                "lease_expires_at": datetime(2026, 7, 18, tzinfo=timezone.utc)
                + timedelta(minutes=5),
            },
            "active_lease",
            False,
        ),
        ({"attempts": 0, "last_error": None}, "not_attempted", False),
        (
            {
                "next_attempt_at": datetime(2026, 7, 18, tzinfo=timezone.utc)
                - timedelta(seconds=1),
            },
            "eligible",
            True,
        ),
        ({"lease_token": uuid4()}, "invalid_lease", False),
    ],
)
def test_storage_deletion_retry_statuses_do_not_mutate_ineligible_rows(
    monkeypatch,
    row_kwargs,
    expected_status,
    retryable,
) -> None:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    row = _retry_row(now, **row_kwargs)
    session = _RetrySession(row, now)
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_backend",
        "local",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "current_storage_scope",
        lambda: "scope",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "validate_key",
        lambda key: None,
    )

    result = storage_deletion_service.inspect_storage_deletion_retry(
        session,
        row.storage_key,
    )

    assert result.status == expected_status
    assert result.retryable is retryable
    assert session.added == []


def test_storage_deletion_retry_rejects_invalid_key_without_query(
    monkeypatch,
) -> None:
    session = _RetrySession(None, None)
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_backend",
        "local",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "current_storage_scope",
        lambda: "scope",
    )
    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "validate_key",
        lambda key: (_ for _ in ()).throw(ValueError("invalid")),
    )

    result = storage_deletion_service.retry_storage_deletion_now(
        session,
        "../invalid",
    )

    assert result.status == "invalid_key"
    assert session.statements == []
    assert session.added == []


def test_enqueue_storage_deletion_rejects_partial_storage_scope() -> None:
    session = _InsertSession()

    with pytest.raises(ValueError, match="provided together"):
        storage_deletion_service.enqueue_storage_deletion(
            session,
            "documents/example.pdf",
            storage_backend="s3",
        )


def test_claim_storage_deletions_assigns_a_finite_lease(monkeypatch) -> None:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    row = StorageDeletion(
        id=uuid4(),
        storage_backend="local",
        storage_scope="local-scope",
        storage_key="documents/example.txt",
        attempts=2,
        next_attempt_at=now,
    )
    session = _ClaimSession(now, [row])
    monkeypatch.setattr(storage_deletion_service, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        storage_deletion_service,
        "set_local_statement_timeout",
        lambda db, timeout: None,
    )
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_deletion_lease_seconds",
        45,
    )

    claims = storage_deletion_service.claim_storage_deletions(limit=1)

    assert len(claims) == 1
    assert claims[0].attempts == 3
    assert claims[0].storage_scope == "local-scope"
    assert claims[0].lease_token == row.lease_token
    assert row.lease_expires_at == now + timedelta(seconds=45)
    assert row.updated_at == now
    assert session.added == [row]
    assert session.committed is True


def test_process_storage_deletion_batch_completes_and_retries(monkeypatch) -> None:
    successful = storage_deletion_service.ClaimedStorageDeletion(
        id=uuid4(),
        storage_backend="local",
        storage_scope="local-scope",
        storage_key="documents/success.txt",
        attempts=1,
        lease_token=uuid4(),
    )
    failing = storage_deletion_service.ClaimedStorageDeletion(
        id=uuid4(),
        storage_backend="local",
        storage_scope="local-scope",
        storage_key="documents/failing.txt",
        attempts=2,
        lease_token=uuid4(),
    )
    completed = []
    failed = []
    monkeypatch.setattr(
        storage_deletion_service,
        "claim_storage_deletions",
        lambda limit=None: [successful, failing],
    )

    def delete_key(key, backend, scope):
        if key == failing.storage_key:
            raise OSError("temporary failure")

    monkeypatch.setattr(
        storage_deletion_service.storage_service,
        "delete_key_for_backend",
        delete_key,
    )
    monkeypatch.setattr(
        storage_deletion_service,
        "complete_storage_deletion",
        lambda claim: completed.append(claim) is None or True,
    )
    monkeypatch.setattr(
        storage_deletion_service,
        "fail_storage_deletion",
        lambda claim, error: failed.append((claim, error)) is None or True,
    )

    result = storage_deletion_service.process_storage_deletion_batch()

    assert result == storage_deletion_service.StorageDeletionBatchResult(
        claimed=2,
        completed=1,
        failed=1,
    )
    assert completed == [successful]
    assert failed[0][0] == failing
    assert isinstance(failed[0][1], OSError)


def test_storage_deletion_retry_delay_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_deletion_retry_base_seconds",
        10,
    )
    monkeypatch.setattr(
        storage_deletion_service.settings,
        "storage_deletion_retry_max_seconds",
        60,
    )

    assert storage_deletion_service.storage_deletion_retry_delay_seconds(1) == 10
    assert storage_deletion_service.storage_deletion_retry_delay_seconds(2) == 20
    assert storage_deletion_service.storage_deletion_retry_delay_seconds(3) == 40
    assert storage_deletion_service.storage_deletion_retry_delay_seconds(4) == 60
    assert storage_deletion_service.storage_deletion_retry_delay_seconds(100) == 60


def test_delete_key_rejects_a_changed_storage_backend(monkeypatch) -> None:
    monkeypatch.setattr(storage_service.settings, "storage_backend", "s3")
    monkeypatch.setattr(
        storage_service,
        "current_storage_scope",
        lambda: "new-scope",
    )

    with pytest.raises(storage_service.StorageBackendChangedError):
        storage_service.delete_key_for_backend(
            "documents/example.txt",
            "local",
            "old-scope",
        )


def test_delete_key_rejects_a_changed_storage_scope(monkeypatch) -> None:
    monkeypatch.setattr(storage_service.settings, "storage_backend", "local")
    monkeypatch.setattr(
        storage_service,
        "current_storage_scope",
        lambda: "new-root",
    )

    with pytest.raises(storage_service.StorageBackendChangedError):
        storage_service.delete_key_for_backend(
            "documents/example.txt",
            "local",
            "old-root",
        )


def test_storage_deletion_retry_bounds_are_validated() -> None:
    with pytest.raises(
        ValueError,
        match="STORAGE_DELETION_RETRY_MAX_SECONDS",
    ):
        Settings(
            storage_deletion_retry_base_seconds=60,
            storage_deletion_retry_max_seconds=30,
        )
