from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes import chat
from app.core.exceptions import register_exception_handlers


class FakeAiLimiter:
    def consume(self, db, *, user_id):
        return None


class FakeSession:
    def rollback(self):
        return None


def test_query_stream_emits_sse_events(monkeypatch) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(chat.router, prefix="/api")
    user_id = uuid4()
    conversation_id = uuid4()

    app.dependency_overrides[authenticated_user_id] = lambda: user_id
    app.dependency_overrides[db_session] = lambda: FakeSession()
    chat.ai_user_rate_limiter = FakeAiLimiter()

    def fake_stream(db, uid, payload):
        yield {
            "type": "meta",
            "conversation_id": str(conversation_id),
        }
        yield {"type": "delta", "text": "你好"}
        yield {
            "type": "done",
            "conversation_id": str(conversation_id),
            "answer": "你好",
            "citations": [],
            "suggested_questions": ["继续"],
        }

    monkeypatch.setattr(chat.chat_service, "query_stream", fake_stream)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/chat/query/stream",
        json={"question": "hello"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = "".join(response.iter_text())

    assert "event: meta" in body
    assert "event: delta" in body
    assert "event: done" in body
    assert str(conversation_id) in body
