"""Prometheus 指标与请求追踪上下文。

标签只使用路由模板、HTTP 状态、Provider 域名等低基数、非敏感值，
不包含用户 ID、文档 ID 或任何业务内容。
"""

from __future__ import annotations

from contextvars import ContextVar
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

http_requests_total = Counter(
    "http_requests_total",
    "Total API requests by method, route template and status",
    ["method", "route", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "API request latency by method and route template",
    ["method", "route"],
)
ai_provider_calls_total = Counter(
    "ai_provider_calls_total",
    "Outbound AI provider HTTP calls by host and status",
    ["host", "status"],
)
ai_provider_call_duration_seconds = Histogram(
    "ai_provider_call_duration_seconds",
    "Outbound AI provider call latency by host",
    ["host"],
)
job_queue_depth = Gauge(
    "job_queue_depth",
    "Persistent jobs by status, refreshed by the recovery supervisor",
    ["status"],
)


def new_request_id() -> str:
    return uuid4().hex


def provider_host(url: str) -> str:
    return urlsplit(url).netloc or "unknown"


def record_provider_call(url: str, started_at: float, status: str) -> None:
    host = provider_host(url)
    ai_provider_calls_total.labels(host=host, status=status).inc()
    ai_provider_call_duration_seconds.labels(host=host).observe(
        perf_counter() - started_at
    )


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
