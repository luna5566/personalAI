import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.deps import db_session
from app.api.routes.auth import router as auth_router
from app.core.exceptions import register_exception_handlers
from app.core.security import LEGACY_PBKDF2_ITERATIONS
from app.schemas.auth import UserLogin
from app.services import auth_service
from app.services.login_rate_limit_service import (
    AuthRateLimitStore,
    RateLimitRule,
    login_scope_hash,
)


class FakeLimiter:
    def __init__(
        self,
        *,
        check_retry_after: int | None = None,
        failure_retry_after: int | None = None,
    ) -> None:
        self.check_result = check_retry_after
        self.failure_result = failure_retry_after
        self.checked: list[tuple[str, str | None]] = []
        self.failures: list[tuple[str, str | None]] = []
        self.cleared: list[str] = []

    def check_retry_after(self, db, *, email, client_host):
        self.checked.append((email, client_host))
        return self.check_result

    def record_failure(self, db, *, email, client_host):
        self.failures.append((email, client_host))
        return self.failure_result

    def clear_account_failures(self, db, *, email):
        self.cleared.append(email)


class FakeSession:
    def __init__(self, user) -> None:
        self.user = user
        self.user_queries = 0
        self.commits = 0

    def scalar(self, statement):
        self.user_queries += 1
        return self.user

    def commit(self):
        self.commits += 1


def _login_payload(password: str = "wrong-password") -> UserLogin:
    return UserLogin(email="User@Example.com", password=password)


def _user():
    from datetime import datetime, timezone

    return SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        password_hash="stored-password-hash",
        name="User",
        avatar_url=None,
        created_at=datetime.now(timezone.utc),
    )


def test_limit_is_checked_before_user_lookup() -> None:
    limiter = FakeLimiter(check_retry_after=37)
    db = FakeSession(_user())

    with pytest.raises(auth_service.LoginRateLimitedError) as exc_info:
        auth_service.login(db, _login_payload(), "192.0.2.10", limiter=limiter)

    assert exc_info.value.retry_after_seconds == 37
    assert db.user_queries == 0
    assert limiter.checked == [("user@example.com", "192.0.2.10")]


def test_unknown_user_runs_dummy_password_check_and_records_failure(monkeypatch) -> None:
    limiter = FakeLimiter()
    db = FakeSession(None)
    captured_hashes: list[str] = []

    def verify(password: str, password_hash: str) -> bool:
        captured_hashes.append(password_hash)
        return False

    monkeypatch.setattr(auth_service, "verify_password", verify)

    with pytest.raises(ValueError, match="邮箱或密码错误"):
        auth_service.login(db, _login_payload(), "192.0.2.10", limiter=limiter)

    assert captured_hashes == [auth_service._DUMMY_PASSWORD_HASH]
    assert limiter.failures == [("user@example.com", "192.0.2.10")]


def test_failure_that_reaches_limit_returns_rate_limit(monkeypatch) -> None:
    limiter = FakeLimiter(failure_retry_after=900)
    db = FakeSession(_user())
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: False)

    with pytest.raises(auth_service.LoginRateLimitedError) as exc_info:
        auth_service.login(db, _login_payload(), "192.0.2.10", limiter=limiter)

    assert exc_info.value.retry_after_seconds == 900
    assert limiter.cleared == []


def test_success_clears_only_account_failures(monkeypatch) -> None:
    user = _user()
    limiter = FakeLimiter()
    db = FakeSession(user)
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: True)
    monkeypatch.setattr(auth_service, "password_needs_rehash", lambda *args: False)
    monkeypatch.setattr(
        auth_service,
        "_issue_access_token",
        lambda *args, **kwargs: "token",
    )

    response = auth_service.login(
        db,
        _login_payload("correct-password"),
        "192.0.2.10",
        limiter=limiter,
    )

    assert response.user.id == user.id
    assert limiter.cleared == ["user@example.com"]
    assert limiter.failures == []
    assert db.commits == 1


def test_successful_legacy_login_rehashes_before_commit(monkeypatch) -> None:
    user = _user()
    password = "legacy-password"
    salt = "0123456789abcdef" * 2
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        LEGACY_PBKDF2_ITERATIONS,
    )
    user.password_hash = f"pbkdf2_sha256${salt}${digest.hex()}"
    limiter = FakeLimiter()
    db = FakeSession(user)
    monkeypatch.setattr(
        auth_service,
        "_issue_access_token",
        lambda *args, **kwargs: "token",
    )

    auth_service.login(
        db,
        _login_payload(password),
        "192.0.2.10",
        limiter=limiter,
    )

    assert user.password_hash.startswith("$argon2id$")
    assert limiter.cleared == ["user@example.com"]
    assert db.commits == 1


def test_wrong_password_never_rehashes_user(monkeypatch) -> None:
    user = _user()
    original_hash = user.password_hash
    limiter = FakeLimiter()
    db = FakeSession(user)
    monkeypatch.setattr(auth_service, "verify_password", lambda *args: False)

    def unexpected_rehash(password_hash: str) -> bool:
        raise AssertionError("failed passwords must not check rehash policy")

    monkeypatch.setattr(auth_service, "password_needs_rehash", unexpected_rehash)

    with pytest.raises(ValueError, match="邮箱或密码错误"):
        auth_service.login(db, _login_payload(), "192.0.2.10", limiter=limiter)

    assert user.password_hash == original_hash
    assert db.commits == 0


def test_login_route_returns_stable_429_with_retry_after(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()

    def limited(db, payload, client_host, client_name):
        assert client_host == "testclient"
        raise auth_service.LoginRateLimitedError(41)

    monkeypatch.setattr(auth_service, "login", limited)
    response = TestClient(app).post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "41"
    assert response.json() == {
        "message": "登录尝试过于频繁，请稍后重试",
        "detail": "登录尝试过于频繁，请稍后重试",
    }


def test_scope_hash_does_not_store_raw_identifier() -> None:
    account_hash = login_scope_hash("account", "user@example.com", "secret")
    client_hash = login_scope_hash("client", "192.0.2.10", "secret")

    assert len(account_hash) == 64
    assert "user@example.com" not in account_hash
    assert account_hash != client_hash


def test_record_only_upserts_request_scopes() -> None:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class RecordSession:
        def __init__(self) -> None:
            self.statements = []
            self.commits = 0

        def scalar(self, statement):
            self.statements.append(statement)
            return now if len(self.statements) == 1 else None

        def commit(self):
            self.commits += 1

    db = RecordSession()
    result = AuthRateLimitStore().record(
        db,
        rules=[
            RateLimitRule(
                scope_hash="a" * 64,
                block_threshold=5,
                window_seconds=900,
                lockout_seconds=900,
            )
        ],
    )

    assert result is None
    assert db.commits == 1
    assert len(db.statements) == 2
    assert str(db.statements[0]).startswith("SELECT now()")
    upsert_sql = str(db.statements[1])
    assert upsert_sql.startswith("INSERT INTO auth_login_attempts")
    assert "ON CONFLICT" in upsert_sql
    assert "DELETE" not in upsert_sql


@pytest.mark.parametrize("password", ["", "x" * 1025])
def test_login_password_length_is_bounded(password: str) -> None:
    with pytest.raises(ValidationError):
        UserLogin(email="user@example.com", password=password)
