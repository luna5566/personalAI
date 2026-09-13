from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.deps import AuthenticatedAccess, authenticated_access, db_session
from app.api.routes.auth import router as auth_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.security import decode_access_token, hash_password, verify_password
from app.models.auth_session import AuthSession
from app.schemas.auth import AuthSessionRead, PasswordChange
from app.services import auth_service


class ScalarRows:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return self.values


class IssueSession:
    def __init__(self, user_id) -> None:
        self.user_id = user_id
        self.executed = []
        self.added = []

    def scalar(self, statement):
        return self.user_id

    def execute(self, statement):
        self.executed.append(statement)

    def add(self, value):
        self.added.append(value)


class LogoutSession:
    def __init__(self) -> None:
        self.executed = []
        self.commits = 0

    def execute(self, statement):
        self.executed.append(statement)

    def commit(self):
        self.commits += 1


class PasswordSession(LogoutSession):
    def __init__(self, user) -> None:
        super().__init__()
        self.user = user

    def scalar(self, statement):
        return self.user


class SessionListDatabase:
    def __init__(self, sessions) -> None:
        self.sessions = sessions
        self.statement = None

    def scalars(self, statement):
        self.statement = statement
        return ScalarRows(self.sessions)


class RevokeSessionDatabase:
    def __init__(self, deleted_session_id) -> None:
        self.deleted_session_id = deleted_session_id
        self.statement = None
        self.commits = 0

    def scalar(self, statement):
        self.statement = statement
        return self.deleted_session_id

    def commit(self):
        self.commits += 1


class PasswordLimiter:
    def __init__(
        self,
        *,
        check_retry_after=None,
        failure_retry_after=None,
    ) -> None:
        self.check_result = check_retry_after
        self.failure_result = failure_retry_after
        self.failures = []
        self.cleared = []

    def check_retry_after(self, db, *, email, client_host):
        return self.check_result

    def record_failure(self, db, *, email, client_host):
        self.failures.append((email, client_host))
        return self.failure_result

    def clear_account_failures(self, db, *, email):
        self.cleared.append(email)


def _user(password: str = "current-password"):
    return SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        password_hash=hash_password(password),
        name="User",
        avatar_url=None,
        created_at=datetime.now(UTC),
    )


def test_session_issue_adds_database_row_matching_strict_jwt() -> None:
    user_id = uuid4()
    db = IssueSession(user_id)
    user = SimpleNamespace(id=user_id)

    token = auth_service._issue_access_token(db, user, client_name="Personal AI Web")
    claims = decode_access_token(token)

    assert len(db.added) == 1
    auth_session = db.added[0]
    assert isinstance(auth_session, AuthSession)
    assert auth_session.id == claims.session_id
    assert auth_session.user_id == claims.user_id == user_id
    assert auth_session.expires_at == claims.expires_at
    assert auth_session.client_name == "Personal AI Web"
    assert len(db.executed) == 1
    delete_statement = db.executed[0]
    compiled = delete_statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "WITH stale_auth_sessions AS" in sql
    assert "DELETE FROM auth_sessions" in sql
    assert "ORDER BY auth_sessions.created_at DESC" in sql
    assert "OFFSET" in sql
    assert "auth_sessions.id" in sql
    assert "auth_sessions.expires_at" not in sql
    assert user_id in compiled.params.values()
    assert settings.auth_max_active_sessions_per_user - 1 in (
        compiled.params.values()
    )
    assert not any(
        isinstance(value, (list, tuple, set))
        for value in compiled.params.values()
    )


def test_session_issue_requires_locked_user_row() -> None:
    db = IssueSession(None)

    with pytest.raises(RuntimeError, match="missing user"):
        auth_service._issue_access_token(db, SimpleNamespace(id=uuid4()))

    assert db.added == []


def test_logout_deletes_only_requested_users_session() -> None:
    db = LogoutSession()

    auth_service.logout(db, user_id=uuid4(), session_id=uuid4())

    assert len(db.executed) == 1
    assert db.commits == 1


def test_logout_all_deletes_every_users_session() -> None:
    db = LogoutSession()

    auth_service.logout_all(db, user_id=uuid4())

    assert len(db.executed) == 1
    assert db.commits == 1


def test_list_sessions_filters_user_and_expiration_and_marks_current() -> None:
    user_id = uuid4()
    current_session_id = uuid4()
    now = datetime.now(UTC)
    sessions = [
        SimpleNamespace(
            id=current_session_id,
            client_name="Personal AI Web",
            created_at=now,
            expires_at=now + timedelta(days=7),
        ),
        SimpleNamespace(
            id=uuid4(),
            client_name=None,
            created_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=7),
        ),
    ]
    db = SessionListDatabase(sessions)

    result = auth_service.list_sessions(
        db,
        user_id=user_id,
        current_session_id=current_session_id,
    )

    assert [item.is_current for item in result] == [True, False]
    assert [item.client_name for item in result] == ["Personal AI Web", None]
    sql = str(db.statement)
    assert "auth_sessions.user_id" in sql
    assert "auth_sessions.expires_at >" in sql
    assert "auth_sessions.created_at DESC" in sql
    assert db.statement._limit_clause.value == (
        settings.auth_max_active_sessions_per_user
    )
    assert user_id in db.statement.compile().params.values()


def test_revoke_session_is_scoped_to_user_and_commits() -> None:
    user_id = uuid4()
    session_id = uuid4()
    db = RevokeSessionDatabase(session_id)

    auth_service.revoke_session(db, user_id=user_id, session_id=session_id)

    sql = str(db.statement)
    assert "auth_sessions.id" in sql
    assert "auth_sessions.user_id" in sql
    assert session_id in db.statement.compile().params.values()
    assert user_id in db.statement.compile().params.values()
    assert db.commits == 1


def test_revoke_missing_or_other_users_session_is_not_found() -> None:
    db = RevokeSessionDatabase(None)

    with pytest.raises(auth_service.AuthSessionNotFoundError, match="登录会话不存在"):
        auth_service.revoke_session(
            db,
            user_id=uuid4(),
            session_id=uuid4(),
        )

    assert db.commits == 0


def test_change_password_replaces_hash_and_all_sessions(monkeypatch) -> None:
    user = _user()
    db = PasswordSession(user)
    limiter = PasswordLimiter()
    monkeypatch.setattr(
        auth_service,
        "_issue_access_token",
        lambda db, user, **kwargs: "replacement-token",
    )

    response = auth_service.change_password(
        db,
        user_id=user.id,
        payload=PasswordChange(
            current_password="current-password",
            new_password="new-password",
        ),
        client_host="192.0.2.10",
        limiter=limiter,
    )

    assert response.access_token == "replacement-token"
    assert verify_password("new-password", user.password_hash)
    assert not verify_password("current-password", user.password_hash)
    assert limiter.cleared == [user.email]
    assert len(db.executed) == 1
    assert db.commits == 1


def test_wrong_current_password_is_counted_without_changing_hash() -> None:
    user = _user()
    original_hash = user.password_hash
    db = PasswordSession(user)
    limiter = PasswordLimiter()

    with pytest.raises(
        auth_service.CurrentPasswordInvalidError,
        match="当前密码错误",
    ):
        auth_service.change_password(
            db,
            user_id=user.id,
            payload=PasswordChange(
                current_password="wrong-password",
                new_password="new-password",
            ),
            client_host="192.0.2.10",
            limiter=limiter,
        )

    assert user.password_hash == original_hash
    assert limiter.failures == [(user.email, "192.0.2.10")]
    assert db.commits == 0


def test_change_password_rejects_reusing_current_password() -> None:
    user = _user()
    db = PasswordSession(user)

    with pytest.raises(auth_service.PasswordReuseError, match="不能与当前密码相同"):
        auth_service.change_password(
            db,
            user_id=user.id,
            payload=PasswordChange(
                current_password="current-password",
                new_password="current-password",
            ),
            limiter=PasswordLimiter(),
        )

    assert db.commits == 0


def test_logout_route_returns_empty_204(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(auth_router)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access
    captured = []

    def logout(db, *, user_id, session_id):
        captured.append((db, user_id, session_id))

    monkeypatch.setattr(auth_service, "logout", logout)
    response = TestClient(app).post("/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    assert len(captured) == 1
    assert captured[0][1:] == (access.user_id, access.session_id)


def test_logout_all_route_returns_empty_204(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(auth_router)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access
    captured = []

    def logout_all(db, *, user_id):
        captured.append((db, user_id))

    monkeypatch.setattr(auth_service, "logout_all", logout_all)
    response = TestClient(app).post("/auth/logout-all")

    assert response.status_code == 204
    assert response.content == b""
    assert len(captured) == 1
    assert captured[0][1] == access.user_id


def test_sessions_route_marks_current_session(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access
    now = datetime.now(UTC)

    def list_sessions(db, *, user_id, current_session_id):
        assert user_id == access.user_id
        assert current_session_id == access.session_id
        return [
            AuthSessionRead(
                id=current_session_id,
                client_name="Personal AI Web",
                created_at=now,
                expires_at=now + timedelta(days=7),
                is_current=True,
            )
        ]

    monkeypatch.setattr(auth_service, "list_sessions", list_sessions)
    response = TestClient(app).get("/auth/sessions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(access.session_id),
            "client_name": "Personal AI Web",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(days=7)).isoformat().replace(
                "+00:00", "Z"
            ),
            "is_current": True,
        }
    ]


def test_revoke_session_route_returns_empty_204(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    target_session_id = uuid4()
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access
    captured = []

    def revoke_session(db, *, user_id, session_id):
        captured.append((user_id, session_id))

    monkeypatch.setattr(auth_service, "revoke_session", revoke_session)
    response = TestClient(app).delete(f"/auth/sessions/{target_session_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert captured == [(access.user_id, target_session_id)]


def test_revoke_other_users_session_route_returns_404(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access

    def missing(db, *, user_id, session_id):
        raise auth_service.AuthSessionNotFoundError("登录会话不存在")

    monkeypatch.setattr(auth_service, "revoke_session", missing)
    response = TestClient(app).delete(f"/auth/sessions/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "登录会话不存在"}


def test_client_name_header_is_normalized_and_bounded(monkeypatch) -> None:
    app = FastAPI(debug=False)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    captured = []

    def login(db, payload, client_host, client_name):
        captured.append(client_name)
        raise auth_service.InvalidCredentialsError("邮箱或密码错误")

    monkeypatch.setattr(auth_service, "login", login)
    response = TestClient(app).post(
        "/auth/login",
        headers={"X-Client-Name": f"  Personal   AI  {'W' * 140}  "},
        json={"email": "user@example.com", "password": "password"},
    )

    assert response.status_code == 401
    assert captured == [f"Personal AI {'W' * 116}"]
    assert len(captured[0]) == 128


def test_login_route_hides_unexpected_value_error(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()

    def fail(db, payload, client_host, client_name):
        raise ValueError("password_hash=C:\\private\\users.db api_key=secret")

    monkeypatch.setattr(auth_service, "login", fail)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/auth/login",
        json={"email": "user@example.com", "password": "password"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "detail": "服务器内部错误",
    }
    assert "private" not in response.text
    assert "api_key" not in response.text


def test_change_password_route_returns_stable_validation_error(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access

    def invalid(db, *, user_id, payload, client_host, client_name):
        raise auth_service.CurrentPasswordInvalidError("当前密码错误")

    monkeypatch.setattr(auth_service, "change_password", invalid)
    response = TestClient(app).post(
        "/auth/change-password",
        json={
            "current_password": "wrong-password",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "当前密码错误"}


def test_change_password_route_returns_retryable_rate_limit(monkeypatch) -> None:
    app = FastAPI(debug=False)
    access = AuthenticatedAccess(user_id=uuid4(), session_id=uuid4())
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    app.dependency_overrides[authenticated_access] = lambda: access

    def limited(db, *, user_id, payload, client_host, client_name):
        raise auth_service.LoginRateLimitedError(57)

    monkeypatch.setattr(auth_service, "change_password", limited)
    response = TestClient(app).post(
        "/auth/change-password",
        json={
            "current_password": "wrong-password",
            "new_password": "new-password",
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "57"
    assert response.json() == {"detail": "登录尝试过于频繁，请稍后重试"}


@pytest.mark.parametrize("new_password", ["", "12345", "x" * 1025])
def test_change_password_schema_bounds_new_password(new_password: str) -> None:
    with pytest.raises(ValueError):
        PasswordChange(
            current_password="current-password",
            new_password=new_password,
        )
