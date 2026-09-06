from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.workers import document_pipeline


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class ScanSession:
    def __init__(self, key_batches, documents) -> None:
        self.key_batches = list(key_batches)
        self.documents = list(documents)
        self.execute_statements = []
        self.scalar_statements = []
        self.events = []
        self.expunged = []

    def execute(self, statement):
        self.execute_statements.append(statement)
        self.events.append("keys")
        return self.key_batches.pop(0)

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        self.events.append("document")
        return self.documents.pop(0)

    def expunge(self, document):
        self.expunged.append(document)
        self.events.append("expunge")

    def rollback(self):
        self.events.append("rollback")


def test_rebuild_scan_uses_bounded_stable_keyset_batches() -> None:
    user_id = uuid4()
    created_before = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    first_row = SimpleNamespace(
        user_id=user_id,
        created_at=created_before - timedelta(minutes=3),
        id=uuid4(),
    )
    second_row = SimpleNamespace(
        user_id=user_id,
        created_at=created_before - timedelta(minutes=2),
        id=uuid4(),
    )
    third_row = SimpleNamespace(
        user_id=user_id,
        created_at=created_before - timedelta(minutes=1),
        id=uuid4(),
    )
    first_document = SimpleNamespace(id=first_row.id)
    third_document = SimpleNamespace(id=third_row.id)
    db = ScanSession(
        [[first_row, second_row], [third_row], []],
        [first_document, None, third_document],
    )

    documents = list(
        document_pipeline._iter_rebuild_documents(
            db,
            user_id=user_id,
            created_before=created_before,
            batch_size=2,
        )
    )

    assert documents == [first_document, third_document]
    assert db.expunged == [first_document, third_document]
    assert len(db.execute_statements) == 3
    assert len(db.scalar_statements) == 3
    first_key_statement = db.execute_statements[0]
    second_key_statement = db.execute_statements[1]
    first_sql = _sql(first_key_statement)
    second_sql = _sql(second_key_statement)
    assert "documents.status IN" in first_sql
    assert "documents.created_at <=" in first_sql
    assert "documents.user_id =" in first_sql
    assert (
        "ORDER BY documents.user_id ASC, documents.created_at ASC, "
        "documents.id ASC" in first_sql
    )
    assert first_key_statement._limit_clause.value == 2
    assert (
        "(documents.user_id, documents.created_at, documents.id) >"
        in second_sql
    )
    second_params = second_key_statement.compile().params.values()
    assert second_row.user_id in second_params
    assert second_row.created_at in second_params
    assert second_row.id in second_params
    assert db.events[:2] == ["keys", "rollback"]
    assert db.events[-1] == "rollback"


def test_rebuild_count_uses_the_same_status_owner_and_snapshot_filters() -> None:
    db = MagicMock()
    db.scalar.return_value = 42
    user_id = uuid4()
    created_before = datetime.now(timezone.utc)

    assert document_pipeline._count_rebuild_documents(
        db,
        user_id=user_id,
        created_before=created_before,
    ) == 42

    statement = db.scalar.call_args.args[0]
    sql = _sql(statement)
    params = statement.compile().params.values()
    assert "count(*)" in sql
    assert "documents.status IN" in sql
    assert "documents.created_at <=" in sql
    assert "documents.user_id =" in sql
    assert user_id in params
    assert created_before in params
    assert set(document_pipeline.REBUILDABLE_DOCUMENT_STATUSES).issubset(
        next(value for value in params if isinstance(value, list))
    )


def test_rebuild_document_is_rechecked_before_being_yielded() -> None:
    user_id = uuid4()
    created_before = datetime.now(timezone.utc)
    row = SimpleNamespace(
        user_id=user_id,
        created_at=created_before - timedelta(seconds=1),
        id=uuid4(),
    )
    db = ScanSession([[row], []], [None])

    assert list(
        document_pipeline._iter_rebuild_documents(
            db,
            user_id=user_id,
            created_before=created_before,
        )
    ) == []

    load_sql = _sql(db.scalar_statements[0])
    assert "documents.id =" in load_sql
    assert "documents.status IN" in load_sql
    assert "documents.created_at <=" in load_sql
    assert "documents.user_id =" in load_sql


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_rebuild_scan_rejects_invalid_batch_size_before_sql(batch_size) -> None:
    db = ScanSession([], [])

    with pytest.raises(ValueError, match="positive integer"):
        list(
            document_pipeline._iter_rebuild_documents(
                db,
                user_id=None,
                created_before=datetime.now(timezone.utc),
                batch_size=batch_size,
            )
        )

    assert db.execute_statements == []
    assert db.scalar_statements == []
