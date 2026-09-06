import json
import logging

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.logging_config import JsonLogFormatter
from app.core.observability import new_request_id, provider_host
from app.main import create_app


def test_metrics_endpoint_exposes_prometheus_payload() -> None:
    client = TestClient(create_app())
    client.get("/api/health")

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "http_requests_total" in body
    assert "/api/health" in body


def test_metrics_endpoint_disabled_by_config(monkeypatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    client = TestClient(create_app())

    response = client.get("/api/metrics")

    assert response.status_code == 404


def test_metrics_use_route_templates_without_ids() -> None:
    client = TestClient(create_app())
    client.get("/api/health")
    client.get("/api/documents/not-a-real-id")

    response = client.get("/api/metrics")
    body = response.text

    # 路由模板允许出现，但具体资源 ID 不允许成为标签。
    assert 'route="/api/documents/{document_id}"' in body
    assert 'route="/api/documents/not-a-real-id"' not in body


def test_request_id_is_returned_and_incoming_value_is_kept() -> None:
    client = TestClient(create_app())

    generated = client.get("/api/health")
    assert generated.headers.get("x-request-id")

    custom = new_request_id()
    echoed = client.get("/api/health", headers={"X-Request-ID": custom})
    assert echoed.headers["x-request-id"] == custom


def test_json_log_formatter_includes_request_id() -> None:
    from app.core.observability import request_id_var

    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1, "结构化日志测试", None, None
    )
    token = request_id_var.set("req-123")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        request_id_var.reset(token)

    assert payload["message"] == "结构化日志测试"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-123"


def test_json_log_formatter_omits_absent_request_id() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        "app.test", logging.WARNING, __file__, 1, "无请求上下文", None, None
    )

    payload = json.loads(formatter.format(record))

    assert "request_id" not in payload


def test_provider_host_is_low_cardinality_and_safe() -> None:
    assert provider_host("https://api.openai.com/v1/chat/completions") == (
        "api.openai.com"
    )
    assert provider_host("not-a-url") == "unknown"
