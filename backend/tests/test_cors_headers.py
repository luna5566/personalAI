from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.request_body_limit import (
    REQUEST_BODY_TOO_LARGE_MESSAGE,
    RequestBodyLimitMiddleware,
)
from app.main import create_app


def test_web_clients_can_read_pagination_and_rebuild_headers() -> None:
    app = create_app()
    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert set(cors.kwargs["expose_headers"]) == {
        "X-Total-Count",
        "X-Embedding-Rebuild-Job-Id",
    }


def test_app_enforces_the_configured_request_body_limit() -> None:
    app = create_app()
    middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is RequestBodyLimitMiddleware
    )

    assert middleware.kwargs["max_body_size_bytes"] > 0


def test_request_body_rejection_keeps_cors_and_private_headers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_request_body_size_bytes", 8)
    app = create_app()

    @app.post("/api/body")
    def body() -> None:
        return None

    response = TestClient(app).post(
        "/api/body",
        content=b"123456789",
        headers={"Origin": "http://127.0.0.1:5600"},
    )

    assert response.status_code == 413
    assert response.json()["message"] == REQUEST_BODY_TOO_LARGE_MESSAGE
    assert response.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:5600"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_api_success_responses_disable_http_caching() -> None:
    app = create_app()

    @app.get("/api/private-response")
    def private_response() -> dict[str, str]:
        return {"access_token": "response-secret"}

    response = TestClient(app).get("/api/private-response")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_api_validation_errors_disable_http_caching() -> None:
    class Payload(BaseModel):
        value: str = Field(max_length=4)

    app = create_app()

    @app.post("/api/validate")
    def validate(payload: Payload) -> None:
        return None

    response = TestClient(app).post("/api/validate", json={"value": "too-long"})

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_api_unhandled_errors_disable_http_caching() -> None:
    app = create_app()

    @app.get("/api/fail")
    def fail() -> None:
        raise RuntimeError("internal response secret")

    response = TestClient(app, raise_server_exceptions=False).get("/api/fail")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_non_api_responses_are_not_forced_to_no_store() -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)

    @app.get("/public")
    def public() -> dict[str, str]:
        return {"status": "public"}

    response = TestClient(app).get("/public")

    assert response.status_code == 200
    assert "cache-control" not in response.headers
    assert "pragma" not in response.headers
