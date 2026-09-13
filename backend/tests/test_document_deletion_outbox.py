from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Delete

from app.api.deps import authenticated_user_id, db_session
from app.api.routes import documents
from app.services import document_service


def test_document_delete_enqueues_storage_before_database_commit(monkeypatch) -> None:
    document_id = uuid4()
    user_id = uuid4()
    reference = SimpleNamespace(
        id=document_id,
        file_path="documents/example.pdf",
        storage_backend="s3",
        storage_scope='{"bucket":"archive"}',
    )
    events = []

    class Result:
        rowcount = 1

    class Session:
        def execute(self, statement):
            assert isinstance(statement, Delete)
            events.append(("delete", None))
            return Result()

        def commit(self):
            events.append(("commit", None))

    monkeypatch.setattr(
        document_service,
        "_get_document_storage_reference",
        lambda db, owner_id, target_id: reference,
    )
    monkeypatch.setattr(
        document_service.storage_deletion_service,
        "enqueue_storage_deletion",
        lambda db, key, **kwargs: events.append(("enqueue", key, kwargs)),
    )

    deleted = document_service.delete_document(
        Session(),
        user_id,
        document_id,
    )

    assert deleted is True
    assert events == [
        (
            "enqueue",
            "documents/example.pdf",
            {
                "storage_backend": "s3",
                "storage_scope": '{"bucket":"archive"}',
            },
        ),
        ("delete", None),
        ("commit", None),
    ]


def test_document_delete_does_not_enqueue_when_document_is_missing(
    monkeypatch,
) -> None:
    events = []
    monkeypatch.setattr(
        document_service,
        "_get_document_storage_reference",
        lambda db, owner_id, target_id: None,
    )
    monkeypatch.setattr(
        document_service.storage_deletion_service,
        "enqueue_storage_deletion",
        lambda db, key, **kwargs: events.append((db, key, kwargs)),
    )

    deleted = document_service.delete_document(
        SimpleNamespace(),
        uuid4(),
        uuid4(),
    )

    assert deleted is False
    assert events == []


def test_document_delete_wakes_the_shared_storage_worker(monkeypatch) -> None:
    notified = []

    class Wakeup:
        def notify(self):
            notified.append(True)

    wakeup = Wakeup()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(storage_deletion_wakeup=wakeup)
        )
    )
    monkeypatch.setattr(documents, "StorageDeletionWakeup", Wakeup)
    monkeypatch.setattr(
        documents.document_service,
        "delete_document",
        lambda db, user_id, document_id: True,
    )

    documents.delete_document(
        uuid4(),
        request,
        SimpleNamespace(),
        uuid4(),
    )

    assert notified == [True]


def test_document_delete_rejects_missing_storage_provenance(monkeypatch) -> None:
    reference = SimpleNamespace(
        file_path="documents/legacy.pdf",
        storage_backend=None,
        storage_scope=None,
    )
    monkeypatch.setattr(
        document_service,
        "_get_document_storage_reference",
        lambda db, owner_id, target_id: reference,
    )

    with pytest.raises(
        document_service.DocumentStorageProvenanceError,
        match="缺少存储位置信息",
    ):
        document_service.delete_document(
            SimpleNamespace(),
            uuid4(),
            uuid4(),
        )


def test_document_delete_route_maps_missing_storage_provenance_to_conflict(
    monkeypatch,
) -> None:
    app = FastAPI(debug=False)
    app.include_router(documents.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_user_id] = uuid4

    def fail(db, user_id, document_id):
        raise document_service.DocumentStorageProvenanceError(
            "资料缺少存储位置信息，暂时不能删除"
        )

    monkeypatch.setattr(document_service, "delete_document", fail)

    response = TestClient(app).delete(f"/documents/{uuid4()}")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "资料缺少存储位置信息，暂时不能删除"
    }
