from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes import chat, organize
from app.core.exceptions import register_exception_handlers
from app.schemas.chat import ChatQueryResponse


class FakeAiLimiter:
    def __init__(self, *, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        self.calls: list[object] = []

    def consume(self, db, *, user_id):
        self.calls.append(user_id)
        return self.retry_after


class FakeSession:
    def rollback(self):
        return None


def _app_with_ai_routes(limiter: FakeAiLimiter) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(chat.router, prefix="/api")
    app.include_router(organize.router, prefix="/api")
    user_id = uuid4()

    def override_user():
        return user_id

    def override_db():
        return FakeSession()

    app.dependency_overrides[authenticated_user_id] = override_user
    app.dependency_overrides[db_session] = override_db
    chat.ai_user_rate_limiter = limiter
    organize.ai_user_rate_limiter = limiter
    return TestClient(app), user_id


def test_chat_query_returns_429_when_ai_quota_exceeded(monkeypatch) -> None:
    limiter = FakeAiLimiter(retry_after=12)
    client, user_id = _app_with_ai_routes(limiter)

    def never_query(*args, **kwargs):
        raise AssertionError("chat service should not run when rate limited")

    monkeypatch.setattr(chat.chat_service, "query", never_query)

    response = client.post(
        "/api/chat/query",
        json={"question": "hello"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"
    assert response.json()["detail"] == "请求过于频繁，请稍后再试"
    assert limiter.calls == [user_id]


def test_organize_document_returns_429_when_ai_quota_exceeded(monkeypatch) -> None:
    limiter = FakeAiLimiter(retry_after=30)
    client, user_id = _app_with_ai_routes(limiter)
    document_id = uuid4()

    def never_organize(*args, **kwargs):
        raise AssertionError("organize service should not run when rate limited")

    monkeypatch.setattr(
        organize.organize_service,
        "organize_document",
        never_organize,
    )

    response = client.post(
        "/api/organize/document",
        json={"document_id": str(document_id), "mode": "summary"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert limiter.calls == [user_id]


def test_chat_query_proceeds_when_quota_available(monkeypatch) -> None:
    limiter = FakeAiLimiter(retry_after=None)
    client, user_id = _app_with_ai_routes(limiter)

    def fake_query(db, uid, payload):
        return ChatQueryResponse(
            conversation_id=uuid4(),
            answer="ok",
            citations=[],
            suggested_questions=[],
        )

    monkeypatch.setattr(chat.chat_service, "query", fake_query)

    response = client.post(
        "/api/chat/query",
        json={"question": "hello"},
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "ok"
    assert limiter.calls == [user_id]


def test_ai_user_rate_limiter_blocks_after_threshold() -> None:
    from app.services.login_rate_limit_service import (
        AiUserRateLimiter,
        AiUserRateLimitPolicy,
        AuthRateLimitStore,
    )

    class RecordingStore(AuthRateLimitStore):
        def __init__(self) -> None:
            self.rules = []
            self._calls = 0

        def record(self, db, *, rules):
            self.rules = rules
            self._calls += 1
            # Mimic block only after threshold is crossed.
            if self._calls > rules[0].block_threshold - 1:
                return 60
            return None

    store = RecordingStore()
    limiter = AiUserRateLimiter(
        secret_key="test-secret",
        policy=AiUserRateLimitPolicy(
            max_requests=2,
            window_seconds=60,
            lockout_seconds=60,
        ),
        store=store,
    )
    user_id = uuid4()
    assert limiter.consume(SimpleNamespace(), user_id=user_id) is None
    assert limiter.consume(SimpleNamespace(), user_id=user_id) is None
    assert limiter.consume(SimpleNamespace(), user_id=user_id) == 60
    assert store.rules[0].block_threshold == 3
