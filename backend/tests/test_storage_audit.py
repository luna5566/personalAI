import tracemalloc
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.services import storage_audit_service
from app.storage import local_storage


class BatchResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class AuditSession:
    def __init__(
        self,
        document_batches: list[list[str]],
        pending_deletion_batches: list[list[str]],
    ) -> None:
        self.document_batches = iter(document_batches)
        self.pending_deletion_batches = iter(pending_deletion_batches)
        self.statements = []
        self.events = []
        self.in_transaction = False
        self._next_id = 1

    def execute(self, statement):
        self.statements.append(statement)
        self.in_transaction = True
        sql = str(statement)
        if "FROM documents" in sql:
            kind = "documents"
            keys = next(self.document_batches, [])
        elif "FROM storage_deletions" in sql:
            kind = "deletions"
            keys = next(self.pending_deletion_batches, [])
        else:
            raise AssertionError(f"unexpected audit SQL: {sql}")
        self.events.append(f"execute:{kind}:{len(keys)}")
        rows = []
        for key in keys:
            rows.append((UUID(int=self._next_id), key))
            self._next_id += 1
        return BatchResult(rows)

    def rollback(self) -> None:
        self.events.append("rollback")
        self.in_transaction = False


class MutationSession:
    def __init__(
        self,
        *,
        expected=False,
        inserted=True,
    ) -> None:
        self.expected = expected
        self.inserted = inserted
        self.statements = []
        self.events = []

    def scalar(self, statement):
        self.statements.append(statement)
        self.events.append("scalar")
        return self.expected

    def execute(self, statement):
        self.statements.append(statement)
        self.events.append("execute")
        value = "created" if self.inserted else None
        return type(
            "Result",
            (),
            {"scalar_one_or_none": lambda self: value},
        )()

    def commit(self) -> None:
        self.events.append("commit")


def _patch_storage_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        storage_audit_service.settings,
        "storage_backend",
        "local",
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "current_storage_scope",
        lambda: '{"root":"current"}',
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "managed_key_prefix",
        lambda: "documents",
    )


def test_local_storage_inventory_is_lazy_read_only_and_scoped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    monkeypatch.setattr(settings, "storage_root", missing_root)

    assert list(local_storage.iter_keys("documents")) == []
    assert local_storage.list_keys("documents") == []
    assert not missing_root.exists()

    documents = missing_root / "documents"
    documents.mkdir(parents=True)
    (documents / "b.txt").write_text("b", encoding="utf-8")
    (documents / "a.txt").write_text("a", encoding="utf-8")
    (missing_root / "outside.txt").write_text("outside", encoding="utf-8")

    assert sorted(local_storage.iter_keys("documents")) == [
        "documents/a.txt",
        "documents/b.txt",
    ]
    assert local_storage.list_keys("documents") == [
        "documents/a.txt",
        "documents/b.txt",
    ]
    assert local_storage.key_exists("documents/a.txt") is True
    assert local_storage.key_exists("documents/missing.txt") is False
    with pytest.raises(ValueError, match="Invalid storage key"):
        local_storage.validate_key("../outside")


def test_storage_audit_uses_short_keyset_batches_and_classifies_drift(
    monkeypatch,
) -> None:
    db = AuditSession(
        document_batches=[
            [
                "documents/present.txt",
                "documents/missing.txt",
            ],
            ["archive/historical.txt", "../invalid.txt"],
        ],
        pending_deletion_batches=[
            ["documents/pending.txt", "../invalid-delete.txt"],
        ],
    )
    existing = {
        "documents/present.txt",
        "archive/historical.txt",
        "documents/pending.txt",
    }
    checked = []
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "list_keys",
        lambda prefix: pytest.fail("audit must not materialize inventory"),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "iter_keys",
        lambda prefix: iter(
            (
                "documents/orphan.txt",
                "documents/pending.txt",
                "documents/present.txt",
            )
        ),
    )

    def validate_key(key: str) -> None:
        checked.append(key)
        if key.startswith("../"):
            raise ValueError("Invalid storage key")

    def key_exists(key: str) -> bool:
        assert db.in_transaction is False
        return key in existing

    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        validate_key,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        key_exists,
    )

    result = storage_audit_service.audit_current_storage(
        db,
        batch_size=2,
        sample_limit=10,
    )

    assert result.is_consistent is False
    assert result.exit_code == 1
    assert result.referenced_count == 4
    assert result.pending_deletion_count == 2
    assert result.inventory_count == 3
    assert result.missing_document_count == 1
    assert result.orphan_count == 1
    assert result.invalid_document_count == 1
    assert result.invalid_pending_deletion_count == 1
    assert result.missing_document_keys == ("documents/missing.txt",)
    assert result.orphan_keys == ("documents/orphan.txt",)
    assert result.invalid_document_keys == ("../invalid.txt",)
    assert result.invalid_pending_deletion_keys == (
        "../invalid-delete.txt",
    )
    assert "archive/historical.txt" in checked
    assert db.events == [
        "execute:documents:2",
        "rollback",
        "execute:documents:2",
        "rollback",
        "execute:documents:0",
        "rollback",
        "execute:deletions:2",
        "rollback",
        "execute:deletions:0",
        "rollback",
    ]
    document_sql = [
        str(statement)
        for statement in db.statements
        if "FROM documents" in str(statement)
    ]
    deletion_sql = [
        str(statement)
        for statement in db.statements
        if "FROM storage_deletions" in str(statement)
    ]
    assert all("ORDER BY documents.id" in sql for sql in document_sql)
    assert all("LIMIT" in sql for sql in document_sql)
    assert "documents.id >" in document_sql[1]
    assert all(
        "ORDER BY storage_deletions.id" in sql for sql in deletion_sql
    )
    assert "storage_deletions.id >" in deletion_sql[1]


def test_storage_audit_deduplicates_expected_keys_on_disk(monkeypatch) -> None:
    db = AuditSession(
        document_batches=[
            ["documents/present.txt", "documents/present.txt"],
        ],
        pending_deletion_batches=[
            ["documents/pending.txt", "documents/present.txt"],
        ],
    )
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "iter_keys",
        lambda prefix: iter(
            ("documents/pending.txt", "documents/present.txt")
        ),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda key: None,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda key: True,
    )

    result = storage_audit_service.audit_current_storage(db, batch_size=2)

    assert result.is_consistent is True
    assert result.exit_code == 0
    assert result.referenced_count == 1
    assert result.pending_deletion_count == 2
    assert result.inventory_count == 2
    assert result.as_dict()["status"] == "consistent"


def test_storage_audit_keeps_exact_counts_and_bounded_stable_samples(
    monkeypatch,
) -> None:
    db = AuditSession(
        document_batches=[
            [
                "archive/missing-z.txt",
                "../invalid-z.txt",
                "archive/missing-a.txt",
                "../invalid-a.txt",
                "archive/missing-m.txt",
            ],
        ],
        pending_deletion_batches=[
            ["../pending-z.txt", "../pending-a.txt", "../pending-m.txt"],
        ],
    )
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "iter_keys",
        lambda prefix: iter(
            (
                "documents/z.txt",
                "documents/b.txt",
                "documents/a.txt",
                "documents/c.txt",
            )
        ),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda key: (
            (_ for _ in ()).throw(ValueError("invalid"))
            if key.startswith("../")
            else None
        ),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda key: False,
    )

    result = storage_audit_service.audit_current_storage(
        db,
        batch_size=10,
        sample_limit=2,
    )
    payload = result.as_dict()

    assert result.missing_document_count == 3
    assert result.missing_document_keys == (
        "archive/missing-a.txt",
        "archive/missing-m.txt",
    )
    assert result.orphan_count == 4
    assert result.orphan_keys == (
        "documents/a.txt",
        "documents/b.txt",
    )
    assert result.invalid_document_count == 2
    assert result.invalid_document_keys == (
        "../invalid-a.txt",
        "../invalid-z.txt",
    )
    assert result.invalid_pending_deletion_count == 3
    assert result.invalid_pending_deletion_keys == (
        "../pending-a.txt",
        "../pending-m.txt",
    )
    assert payload["sample_limit"] == 2
    assert payload["diagnostics_truncated"] == {
        "missing_document_keys": True,
        "orphan_keys": True,
        "invalid_document_keys": False,
        "invalid_pending_deletion_keys": True,
    }


def test_storage_audit_inventory_memory_does_not_grow_with_key_count(
    monkeypatch,
) -> None:
    db = AuditSession(document_batches=[], pending_deletion_batches=[])
    _patch_storage_identity(monkeypatch)
    inventory_size = 20_000

    def inventory(prefix):
        for index in range(inventory_size - 1, -1, -1):
            yield f"documents/{index:08d}.txt"

    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "iter_keys",
        inventory,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda key: None,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda key: True,
    )

    tracemalloc.start()
    try:
        result = storage_audit_service.audit_current_storage(
            db,
            batch_size=100,
            sample_limit=5,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.inventory_count == inventory_size
    assert result.orphan_count == inventory_size
    assert result.orphan_keys == (
        "documents/00000000.txt",
        "documents/00000001.txt",
        "documents/00000002.txt",
        "documents/00000003.txt",
        "documents/00000004.txt",
    )
    assert peak_bytes < 5 * 1024 * 1024


@pytest.mark.parametrize(
    ("batch_size", "sample_limit"),
    [(0, 1), (True, 1), (1, -1), (1, True)],
)
def test_storage_audit_rejects_invalid_limits_before_io(
    batch_size,
    sample_limit,
) -> None:
    with pytest.raises(ValueError):
        storage_audit_service.audit_current_storage(
            object(),
            batch_size=batch_size,
            sample_limit=sample_limit,
        )


def test_exact_orphan_inspection_does_not_scan_inventory(monkeypatch) -> None:
    key = "documents/orphan.txt"
    db = MutationSession(expected=False)
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "iter_keys",
        lambda prefix: pytest.fail("single-key inspection must not scan"),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda value: db.events.append("validate"),
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda value: db.events.append("exists") or True,
    )

    inspection = storage_audit_service.inspect_orphan_status(db, key)

    assert inspection.is_orphan is True
    assert inspection.as_dict() == {
        "status": "orphan",
        "storage_backend": "local",
        "storage_scope": '{"root":"current"}',
        "storage_key": key,
    }
    assert db.events == ["validate", "exists", "scalar"]
    assert len(db.statements) == 1
    inspection_sql = str(db.statements[0])
    assert "EXISTS" in inspection_sql
    assert "md5(documents.file_path)" in inspection_sql
    assert "documents.file_path" in inspection_sql
    assert "storage_deletions.storage_key" in inspection_sql


def test_orphan_deletion_is_enqueued_after_exact_check(monkeypatch) -> None:
    key = "documents/orphan.txt"
    db = MutationSession()
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda value: None,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda value: db.events.append("exists") or True,
    )

    receipt = storage_audit_service.enqueue_orphan_deletion(db, key)

    assert db.events == ["exists", "scalar", "execute", "commit"]
    assert len(db.statements) == 2
    compiled = db.statements[1].compile(dialect=postgresql.dialect())
    assert compiled.params["storage_backend"] == "local"
    assert compiled.params["storage_scope"] == '{"root":"current"}'
    assert compiled.params["storage_key"] == key
    assert receipt.as_dict() == {
        "status": "queued",
        "storage_backend": "local",
        "storage_scope": '{"root":"current"}',
        "storage_key": key,
    }


def test_orphan_deletion_reports_concurrent_existing_intent(
    monkeypatch,
) -> None:
    key = "documents/orphan.txt"
    db = MutationSession(inserted=False)
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda value: None,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda value: True,
    )

    receipt = storage_audit_service.enqueue_orphan_deletion(db, key)

    assert db.events == ["scalar", "execute", "commit"]
    assert receipt.created is False
    assert receipt.as_dict()["status"] == "already_queued"


@pytest.mark.parametrize(
    ("key", "valid", "exists", "expected", "events"),
    [
        ("archive/outside.txt", True, True, False, []),
        ("documents/invalid.txt", False, True, False, ["validate"]),
        (
            "documents/missing.txt",
            True,
            False,
            False,
            ["validate", "exists"],
        ),
        (
            "documents/referenced.txt",
            True,
            True,
            True,
            ["validate", "exists", "scalar"],
        ),
    ],
)
def test_orphan_inspection_rejects_non_orphans_without_mutation(
    monkeypatch,
    key,
    valid,
    exists,
    expected,
    events,
) -> None:
    db = MutationSession(expected=expected)
    _patch_storage_identity(monkeypatch)

    def validate_key(value: str) -> None:
        db.events.append("validate")
        if not valid:
            raise ValueError("invalid")

    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        validate_key,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda value: db.events.append("exists") or exists,
    )

    inspection = storage_audit_service.inspect_orphan_status(db, key)

    assert inspection.is_orphan is False
    assert db.events == events
    assert "execute" not in db.events
    assert "commit" not in db.events


def test_enqueue_rejects_expected_key_without_insert(monkeypatch) -> None:
    key = "documents/referenced.txt"
    db = MutationSession(expected=True)
    _patch_storage_identity(monkeypatch)
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "validate_key",
        lambda value: None,
    )
    monkeypatch.setattr(
        storage_audit_service.storage_service,
        "key_exists",
        lambda value: True,
    )

    with pytest.raises(
        storage_audit_service.StorageObjectNotOrphanError,
        match="不是当前存储审计中的孤立对象",
    ):
        storage_audit_service.enqueue_orphan_deletion(db, key)

    assert db.events == ["scalar"]
    assert len(db.statements) == 1
