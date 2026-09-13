from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.deps import AuthenticatedAccess, authenticated_access, db_session
from app.api.routes import auth as auth_routes
from app.core.security import hash_password
from app.schemas.auth import AccountDelete
from app.services import auth_service


class _AccountDeletionSession:
    def __init__(self, user, *, missing_storage_provenance=False):
        self.user = user
        self.missing_storage_provenance = missing_storage_provenance
        self.scalar_statements = []
        self.executed = []
        self.deleted = []
        self.commits = 0

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        if len(self.scalar_statements) == 1:
            return self.user
        if "EXISTS" in str(statement):
            return self.missing_storage_provenance
        return 0

    def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=1)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1


class _Limiter:
    def __init__(self, check_result=None, failure_result=None):
        self.check_result = check_result
        self.failure_result = failure_result
        self.failures = []
        self.cleared = []

    def check_retry_after(self, db, *, email, client_host):
        return self.check_result

    def record_failure(self, db, *, email, client_host):
        self.failures.append((email, client_host))
        return self.failure_result

    def clear_account_failures(self, db, *, email):
        self.cleared.append(email)


def _user(password="current-password"):
    return SimpleNamespace(
        id=uuid4(),
        email="delete-me@example.com",
        password_hash=hash_password(password),
        name="Delete Me",
        avatar_url=None,
        created_at=datetime.now(UTC),
    )


def test_delete_account_enqueues_unique_files_and_deletes_owned_rows(
    monkeypatch,
) -> None:
    user = _user()
    db = _AccountDeletionSession(user)
    limiter = _Limiter()
    monkeypatch.setattr(
        auth_service.settings,
        "runtime_settings_admin_user_id",
        uuid4(),
    )
    monkeypatch.setattr(
        auth_service,
        "_has_user_data_ownership_conflict",
        lambda db, user_id: False,
    )

    auth_service.delete_account(
        db,
        user_id=user.id,
        payload=AccountDelete(
            current_password="current-password",
            confirmation="DELETE",
        ),
        client_host="192.0.2.10",
        limiter=limiter,
    )

    assert len(db.scalar_statements) == 4
    lock_statements = db.scalar_statements[1:3]
    assert all("FOR UPDATE" in str(statement) for statement in lock_statements)
    assert all("count(*)" in str(statement) for statement in lock_statements)
    assert "jobs.id" in str(lock_statements[0])
    document_lock_sql = str(lock_statements[1])
    assert "documents.id" in document_lock_sql
    assert "documents.raw_text" not in document_lock_sql
    assert "EXISTS" in str(db.scalar_statements[3])

    outbox_sql = str(
        db.executed[0].compile(dialect=postgresql.dialect())
    )
    assert "INSERT INTO storage_deletions" in outbox_sql
    assert "SELECT DISTINCT" in outbox_sql
    assert "gen_random_uuid()" in outbox_sql
    assert (
        "ON CONFLICT ON CONSTRAINT uq_storage_deletions_location_key "
        "DO NOTHING"
    ) in outbox_sql
    deleted_tables = [
        statement.table.name
        for statement in db.executed
        if statement.is_delete
    ]
    assert deleted_tables == [
        "chunk_embeddings",
        "document_chunks",
        "messages",
        "jobs",
        "conversations",
        "documents",
        "tags",
    ]
    assert db.deleted == [user]
    assert db.commits == 1
    assert limiter.cleared == [user.email]


def test_delete_account_rejects_mixed_missing_storage_provenance(
    monkeypatch,
) -> None:
    user = _user()
    db = _AccountDeletionSession(
        user,
        missing_storage_provenance=True,
    )
    monkeypatch.setattr(
        auth_service.settings,
        "runtime_settings_admin_user_id",
        uuid4(),
    )
    monkeypatch.setattr(
        auth_service,
        "_has_user_data_ownership_conflict",
        lambda db, user_id: False,
    )

    with pytest.raises(
        auth_service.AccountDataOwnershipError,
        match="缺少存储位置信息",
    ):
        auth_service.delete_account(
            db,
            user_id=user.id,
            payload=AccountDelete(
                current_password="current-password",
                confirmation="DELETE",
            ),
            limiter=_Limiter(),
        )

    assert db.executed == []
    assert db.deleted == []
    assert db.commits == 0


def test_delete_account_rejects_wrong_password_without_mutation(monkeypatch) -> None:
    user = _user()
    db = _AccountDeletionSession(user)
    limiter = _Limiter()
    monkeypatch.setattr(
        auth_service.settings,
        "runtime_settings_admin_user_id",
        uuid4(),
    )

    with pytest.raises(
        auth_service.CurrentPasswordInvalidError,
        match="当前密码错误",
    ):
        auth_service.delete_account(
            db,
            user_id=user.id,
            payload=AccountDelete(
                current_password="wrong-password",
                confirmation="DELETE",
            ),
            client_host="192.0.2.10",
            limiter=limiter,
        )

    assert limiter.failures == [(user.email, "192.0.2.10")]
    assert db.executed == []
    assert db.deleted == []
    assert db.commits == 0


def test_delete_account_preserves_configured_admin() -> None:
    user = _user()
    db = _AccountDeletionSession(user)

    original_admin_id = auth_service.settings.runtime_settings_admin_user_id
    try:
        auth_service.settings.runtime_settings_admin_user_id = user.id
        with pytest.raises(
            auth_service.AdminAccountDeletionError,
            match="管理员账号不能自助删除",
        ):
            auth_service.delete_account(
                db,
                user_id=user.id,
                payload=AccountDelete(
                    current_password="current-password",
                    confirmation="DELETE",
                ),
            )
    finally:
        auth_service.settings.runtime_settings_admin_user_id = original_admin_id

    assert db.executed == []
    assert db.deleted == []
    assert db.commits == 0


def test_delete_account_stops_on_ownership_conflict(monkeypatch) -> None:
    user = _user()
    db = _AccountDeletionSession(user)
    monkeypatch.setattr(
        auth_service.settings,
        "runtime_settings_admin_user_id",
        uuid4(),
    )
    monkeypatch.setattr(
        auth_service,
        "_has_user_data_ownership_conflict",
        lambda db, user_id: True,
    )

    with pytest.raises(
        auth_service.AccountDataOwnershipError,
        match="账号数据归属异常",
    ):
        auth_service.delete_account(
            db,
            user_id=user.id,
            payload=AccountDelete(
                current_password="current-password",
                confirmation="DELETE",
            ),
            limiter=_Limiter(),
        )

    assert db.executed == []
    assert db.deleted == []
    assert db.commits == 0


def test_delete_account_route_returns_204_and_wakes_storage_worker(
    monkeypatch,
) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_routes.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access
    captured = []
    notified = []

    class Wakeup:
        def notify(self):
            notified.append(True)

    app.state.storage_deletion_wakeup = Wakeup()
    monkeypatch.setattr(auth_routes, "StorageDeletionWakeup", Wakeup)

    def delete_account(db, *, user_id, payload, client_host):
        captured.append((user_id, payload, client_host))

    monkeypatch.setattr(auth_service, "delete_account", delete_account)
    response = TestClient(app).request(
        "DELETE",
        "/auth/account",
        json={
            "current_password": "current-password",
            "confirmation": "DELETE",
        },
    )

    assert response.status_code == 204
    assert response.content == b""
    assert captured[0][0] == access.user_id
    assert captured[0][1].current_password == "current-password"
    assert notified == [True]


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (
            auth_service.CurrentPasswordInvalidError("当前密码错误"),
            400,
            "当前密码错误",
        ),
        (
            auth_service.AdminAccountDeletionError("管理员账号不能自助删除"),
            409,
            "管理员账号不能自助删除",
        ),
        (
            auth_service.AccountDataOwnershipError("账号数据归属异常"),
            409,
            "账号数据归属异常",
        ),
        (
            auth_service.UserNotFoundError("用户不存在"),
            404,
            "用户不存在",
        ),
    ],
)
def test_delete_account_route_maps_stable_errors(
    monkeypatch,
    error,
    status_code,
    detail,
) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_routes.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access

    def fail(db, *, user_id, payload, client_host):
        raise error

    monkeypatch.setattr(auth_service, "delete_account", fail)
    response = TestClient(app).request(
        "DELETE",
        "/auth/account",
        json={
            "current_password": "current-password",
            "confirmation": "DELETE",
        },
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}


def test_delete_account_route_returns_retry_after(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_routes.router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access

    def limited(db, *, user_id, payload, client_host):
        raise auth_service.LoginRateLimitedError(73)

    monkeypatch.setattr(auth_service, "delete_account", limited)
    response = TestClient(app).request(
        "DELETE",
        "/auth/account",
        json={
            "current_password": "current-password",
            "confirmation": "DELETE",
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "73"


@pytest.mark.parametrize(
    "payload",
    [
        {"current_password": "", "confirmation": "DELETE"},
        {"current_password": "password", "confirmation": "delete"},
        {"current_password": "x" * 1025, "confirmation": "DELETE"},
    ],
)
def test_account_delete_schema_rejects_invalid_confirmation(payload) -> None:
    with pytest.raises(ValueError):
        AccountDelete(**payload)
