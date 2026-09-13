import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException
from starlette.requests import Request

from app.core.exceptions import (
    DATABASE_UNAVAILABLE_MESSAGE,
    database_unavailable_handler,
    http_exception_handler,
    register_exception_handlers,
    unhandled_exception_handler,
    validation_exception_handler,
)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_http_error_contains_stable_message() -> None:
    response = asyncio.run(http_exception_handler(_request(), HTTPException(401, "需要登录")))
    body = json.loads(response.body)

    assert response.status_code == 401
    assert body == {"message": "需要登录", "detail": "需要登录"}


def test_validation_error_contains_stable_message() -> None:
    error = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "title"),
                "msg": "Field required provider api_key=secret",
                "input": {"password": "request-secret"},
                "ctx": {"error": ValueError("provider api_key=secret")},
                "url": "https://errors.example/internal",
            }
        ]
    )
    response = asyncio.run(validation_exception_handler(_request(), error))
    body = json.loads(response.body)

    assert response.status_code == 422
    assert body["message"] == "缺少必填字段"
    assert body["detail"] == [
        {
            "type": "missing",
            "loc": ["body", "title"],
            "msg": "缺少必填字段",
        }
    ]
    assert "Field required" not in response.body.decode()
    assert "request-secret" not in response.body.decode()
    assert "api_key" not in response.body.decode()
    assert "errors.example" not in response.body.decode()


def test_validation_error_does_not_echo_sensitive_request_values() -> None:
    class SensitivePayload(BaseModel):
        password: str = Field(max_length=8)
        api_key: str = Field(max_length=8)

    app = FastAPI(debug=False)
    register_exception_handlers(app)

    @app.post("/validate")
    def validate(payload: SensitivePayload) -> None:
        return None

    password = "password-secret-marker"
    api_key = "api-key-secret-marker"
    response = TestClient(app).post(
        "/validate",
        json={"password": password, "api_key": api_key},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "文本长度超过限制"
    assert len(body["detail"]) == 2
    assert all(set(error) == {"type", "loc", "msg"} for error in body["detail"])
    assert {error["msg"] for error in body["detail"]} == {"文本长度超过限制"}
    assert password not in response.text
    assert api_key not in response.text


@pytest.mark.parametrize(
    ("error_type", "location", "expected_message"),
    [
        ("value_error", ("body", "email"), "邮箱格式无效"),
        ("uuid_parsing", ("body", "document_id"), "ID 格式无效"),
        ("enum", ("body", "mode"), "输入值不在允许范围内"),
        ("literal_error", ("body", "confirmation"), "输入值不符合要求"),
        ("int_parsing", ("query", "page"), "请输入有效整数"),
        ("greater_than_equal", ("query", "page"), "数值低于允许范围"),
        ("less_than_equal", ("query", "page_size"), "数值超过允许范围"),
        ("too_long", ("body", "document_ids"), "项目数量超过限制"),
        ("future_pydantic_error", ("body", "value"), "请求参数不合法"),
    ],
)
def test_validation_error_messages_are_stable_and_localized(
    error_type,
    location,
    expected_message,
) -> None:
    internal_message = "Pydantic internal provider api_key=secret"
    error = RequestValidationError(
        [
            {
                "type": error_type,
                "loc": location,
                "msg": internal_message,
                "input": "request-secret",
            }
        ]
    )

    response = asyncio.run(validation_exception_handler(_request(), error))
    body = json.loads(response.body)

    assert body == {
        "message": expected_message,
        "detail": [
            {
                "type": error_type,
                "loc": list(location),
                "msg": expected_message,
            }
        ],
    }
    assert internal_message not in response.body.decode()
    assert "request-secret" not in response.body.decode()


def test_unhandled_error_does_not_leak_internal_details() -> None:
    response = asyncio.run(
        unhandled_exception_handler(_request(), RuntimeError("provider secret"))
    )
    body = json.loads(response.body)

    assert response.status_code == 500
    assert body == {"message": "服务器内部错误", "detail": "服务器内部错误"}


def test_unhandled_error_is_json_through_asgi_middleware() -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)

    @app.get("/fail")
    def fail() -> None:
        raise RuntimeError("provider secret")

    response = TestClient(app, raise_server_exceptions=False).get("/fail")

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "detail": "服务器内部错误",
    }
    assert "provider secret" not in response.text


@pytest.mark.parametrize(
    "error",
    [
        OperationalError(
            "SELECT api_key FROM secrets",
            {"api_key": "database secret"},
            RuntimeError("database host leaked here"),
        ),
        SQLAlchemyTimeoutError("pool details leaked here"),
    ],
)
def test_database_errors_return_stable_retryable_response(error) -> None:
    response = asyncio.run(database_unavailable_handler(_request(), error))
    body = json.loads(response.body)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert body == {
        "message": DATABASE_UNAVAILABLE_MESSAGE,
        "detail": DATABASE_UNAVAILABLE_MESSAGE,
    }
    assert "secret" not in response.body.decode()
    assert "pool" not in response.body.decode()


def test_database_error_is_503_through_asgi_middleware() -> None:
    app = FastAPI(debug=False)
    register_exception_handlers(app)

    @app.get("/database-fail")
    def fail() -> None:
        raise OperationalError(
            "SELECT password FROM users",
            {"password": "database secret"},
            RuntimeError("database host leaked here"),
        )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/database-fail"
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json() == {
        "message": DATABASE_UNAVAILABLE_MESSAGE,
        "detail": DATABASE_UNAVAILABLE_MESSAGE,
    }
    assert "password" not in response.text
    assert "secret" not in response.text
