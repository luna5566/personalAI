from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.deps import db_session
from app.api.routes.auth import router as auth_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.schemas.auth import UserRegister
from app.services import auth_service
from app.services.login_rate_limit_service import (
    RegistrationRateLimiter,
    RegistrationRateLimitPolicy,
    login_scope_hash,
)


class FakeRegistrationLimiter:
    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        self.consumed: list[str | None] = []

    def consume(self, db, *, client_host):
        self.consumed.append(client_host)
        return self.retry_after


class FakeRateLimitStore:
    def __init__(self, result: int | None = None) -> None:
        self.result = result
        self.calls = []

    def record(self, db, *, rules):
        self.calls.append((db, rules))
        return self.result


class FakeSession:
    def __init__(self, *, existing=None, commit_error: Exception | None = None) -> None:
        self.existing = existing
        self.commit_error = commit_error
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshes = 0
        self.flushes = 0
        self.scalar_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.existing

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def flush(self) -> None:
        self.flushes += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, value) -> None:
        self.refreshes += 1


def _payload() -> UserRegister:
    return UserRegister(
        email="User@Example.com",
        password="secure-password",
        name="User",
    )


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    original = RuntimeError("database detail must not reach the response")
    original.diag = SimpleNamespace(constraint_name=constraint_name)
    return IntegrityError(
        "INSERT INTO users",
        {"email": "user@example.com"},
        original,
    )


def test_existing_email_uses_fast_path_before_password_hash(monkeypatch) -> None:
    db = FakeSession(existing=object())
    limiter = FakeRegistrationLimiter()

    def unexpected_hash(password: str) -> str:
        raise AssertionError("existing users must not trigger Argon2")

    monkeypatch.setattr(auth_service, "hash_password", unexpected_hash)

    with pytest.raises(auth_service.EmailAlreadyRegisteredError, match="邮箱已注册"):
        auth_service.register(
            db,
            _payload(),
            "192.0.2.10",
            limiter=limiter,
        )

    assert limiter.consumed == ["192.0.2.10"]
    assert db.added == []
    assert db.commits == 0


def test_email_unique_race_rolls_back_and_returns_domain_error(monkeypatch) -> None:
    error = _integrity_error("uq_users_email")
    db = FakeSession(commit_error=error)
    limiter = FakeRegistrationLimiter()
    monkeypatch.setattr(auth_service, "hash_password", lambda password: "hash")

    with pytest.raises(auth_service.EmailAlreadyRegisteredError) as exc_info:
        auth_service.register(db, _payload(), limiter=limiter)

    assert str(exc_info.value) == "邮箱已注册"
    assert exc_info.value.__cause__ is error
    assert db.flushes == 1
    assert db.commits == 0
    assert db.rollbacks == 1
    assert db.refreshes == 0


@pytest.mark.parametrize("constraint_name", [None, "some_other_constraint"])
def test_other_integrity_errors_are_rolled_back_and_reraised(
    constraint_name: str | None,
    monkeypatch,
) -> None:
    error = _integrity_error(constraint_name)
    db = FakeSession(commit_error=error)
    limiter = FakeRegistrationLimiter()
    monkeypatch.setattr(auth_service, "hash_password", lambda password: "hash")

    with pytest.raises(IntegrityError) as exc_info:
        auth_service.register(db, _payload(), limiter=limiter)

    assert exc_info.value is error
    assert db.flushes == 1
    assert db.commits == 0
    assert db.rollbacks == 1
    assert db.refreshes == 0


def test_registration_conflict_route_returns_stable_409(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()

    def duplicate(db, payload, client_host, client_name):
        assert client_host == "testclient"
        raise auth_service.EmailAlreadyRegisteredError("邮箱已注册")

    monkeypatch.setattr(auth_service, "register", duplicate)
    response = TestClient(app).post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "secure-password",
            "name": "User",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "message": "邮箱已注册",
        "detail": "邮箱已注册",
    }
    assert "database detail" not in response.text


def test_auth_config_route_exposes_registration_policy(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    monkeypatch.setattr(settings, "auth_registration_enabled", False)

    response = TestClient(app).get("/auth/config")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "registration_enabled": False,
        "invitation_required": False,
    }


def test_disabled_registration_returns_403_before_service_call(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()
    monkeypatch.setattr(settings, "auth_registration_enabled", False)

    def unexpected_register(*args, **kwargs):
        raise AssertionError("disabled registration must not enter the service")

    monkeypatch.setattr(auth_service, "register", unexpected_register)
    response = TestClient(app).post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "secure-password",
            "name": "User",
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "message": "当前不开放新账号注册",
        "detail": "当前不开放新账号注册",
    }


def test_invalid_invite_route_returns_stable_403(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()

    def invalid_invite(db, payload, client_host, client_name):
        raise auth_service.RegistrationInviteInvalidError("邀请码无效或已过期")

    monkeypatch.setattr(auth_service, "register", invalid_invite)
    response = TestClient(app).post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "secure-password",
            "name": "User",
            "invite_code": "invalid-code",
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "message": "邀请码无效或已过期",
        "detail": "邀请码无效或已过期",
    }


def test_registration_limit_is_consumed_before_user_lookup(monkeypatch) -> None:
    db = FakeSession()
    limiter = FakeRegistrationLimiter(retry_after=37)

    def unexpected_hash(password: str) -> str:
        raise AssertionError("limited requests must not trigger Argon2")

    monkeypatch.setattr(auth_service, "hash_password", unexpected_hash)

    with pytest.raises(auth_service.RegistrationRateLimitedError) as exc_info:
        auth_service.register(
            db,
            _payload(),
            "192.0.2.10",
            limiter=limiter,
        )

    assert exc_info.value.retry_after_seconds == 37
    assert limiter.consumed == ["192.0.2.10"]
    assert db.scalar_calls == 0
    assert db.added == []


def test_registration_rate_limiter_allows_configured_attempts_before_block() -> None:
    store = FakeRateLimitStore(result=3600)
    policy = RegistrationRateLimitPolicy(
        client_max_attempts=5,
        window_seconds=3600,
        lockout_seconds=3600,
    )
    limiter = RegistrationRateLimiter(
        secret_key="secret",
        policy=policy,
        store=store,
    )
    db = object()

    assert limiter.consume(db, client_host="192.0.2.10") == 3600

    recorded_db, rules = store.calls[0]
    assert recorded_db is db
    assert len(rules) == 1
    assert rules[0].scope_hash == login_scope_hash(
        "registration-client",
        "192.0.2.10",
        "secret",
    )
    assert rules[0].block_threshold == 6
    assert rules[0].window_seconds == 3600
    assert rules[0].lockout_seconds == 3600


def test_registration_limit_route_returns_stable_429(monkeypatch) -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[db_session] = lambda: object()

    def limited(db, payload, client_host, client_name):
        assert client_host == "testclient"
        raise auth_service.RegistrationRateLimitedError(43)

    monkeypatch.setattr(auth_service, "register", limited)
    response = TestClient(app).post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "secure-password",
            "name": "User",
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "43"
    assert response.json() == {
        "message": "注册请求过于频繁，请稍后重试",
        "detail": "注册请求过于频繁，请稍后重试",
    }
