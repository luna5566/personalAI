from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.request_body_limit import (
    REQUEST_BODY_TOO_LARGE_MESSAGE,
    RequestBodyLimitMiddleware,
)


def _body_client(limit: int, received: list[bytes]) -> TestClient:
    app = FastAPI(debug=False)

    @app.post("/body")
    async def consume_body(request: Request) -> dict[str, int]:
        body = await request.body()
        received.append(body)
        return {"size": len(body)}

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_size_bytes=limit,
    )
    return TestClient(app)


def test_content_length_over_limit_is_rejected_before_endpoint() -> None:
    received: list[bytes] = []

    response = _body_client(8, received).post("/body", content=b"123456789")

    assert response.status_code == 413
    assert response.json() == {
        "message": REQUEST_BODY_TOO_LARGE_MESSAGE,
        "detail": REQUEST_BODY_TOO_LARGE_MESSAGE,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert received == []


def test_chunked_body_over_limit_is_rejected_before_endpoint() -> None:
    received: list[bytes] = []

    def chunks() -> Iterator[bytes]:
        yield b"1234"
        yield b"56789"

    response = _body_client(8, received).post("/body", content=chunks())

    assert response.request.headers["transfer-encoding"] == "chunked"
    assert response.status_code == 413
    assert response.json()["message"] == REQUEST_BODY_TOO_LARGE_MESSAGE
    assert received == []


def test_body_at_exact_limit_is_accepted() -> None:
    received: list[bytes] = []

    response = _body_client(8, received).post("/body", content=b"12345678")

    assert response.status_code == 200
    assert response.json() == {"size": 8}
    assert received == [b"12345678"]
