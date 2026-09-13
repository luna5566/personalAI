from fastapi import Request
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import _is_loopback_client, create_app


def _request_with_client(host: str | None) -> Request:
    scope = {
        "type": "http",
        "client": None if host is None else (host, 12345),
    }
    return Request(scope)


def test_metrics_open_in_local_environment_by_default() -> None:
    client = TestClient(create_app())

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_metrics_hidden_from_remote_clients_in_deployed_environments(
    monkeypatch,
) -> None:
    previous_env = settings.app_env
    settings.app_env = "production"
    try:
        client = TestClient(create_app())

        response = client.get("/api/metrics")

        assert response.status_code == 404
    finally:
        settings.app_env = previous_env


def test_metrics_require_local_can_be_disabled_behind_proxy(monkeypatch) -> None:
    previous_env = settings.app_env
    previous_flag = settings.metrics_require_local
    settings.app_env = "production"
    settings.metrics_require_local = False
    try:
        client = TestClient(create_app())

        response = client.get("/api/metrics")

        assert response.status_code == 200
    finally:
        settings.app_env = previous_env
        settings.metrics_require_local = previous_flag


def test_is_loopback_client_matches_only_loopback_hosts() -> None:
    assert _is_loopback_client(_request_with_client("127.0.0.1"))
    assert _is_loopback_client(_request_with_client("::1"))
    assert _is_loopback_client(_request_with_client("localhost"))
    assert not _is_loopback_client(_request_with_client("10.1.2.3"))
    assert not _is_loopback_client(_request_with_client(None))
