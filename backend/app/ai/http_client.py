from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


PROVIDER_RESPONSE_READ_CHUNK_BYTES = 64 * 1024


class ProviderResponseTooLargeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderRequestLimiterSnapshot:
    max_concurrent_requests: int
    active_requests: int
    waiting_requests: int


class ProviderRequestLimiter:
    def __init__(self, max_concurrent_requests: int) -> None:
        if (
            type(max_concurrent_requests) is not int
            or max_concurrent_requests < 1
        ):
            raise ValueError(
                "Provider request concurrency limit must be a positive integer"
            )
        self._max_concurrent_requests = max_concurrent_requests
        self._condition = threading.Condition()
        self._active_requests = 0
        self._waiters: deque[object] = deque()

    @contextmanager
    def reserve(self) -> Iterator[None]:
        ticket = object()
        with self._condition:
            self._waiters.append(ticket)
            try:
                while (
                    self._active_requests >= self._max_concurrent_requests
                    or self._waiters[0] is not ticket
                ):
                    self._condition.wait()
                granted = self._waiters.popleft()
                if granted is not ticket:
                    raise RuntimeError(
                        "Provider request limiter queue order was corrupted"
                    )
                self._active_requests += 1
            except BaseException:
                try:
                    self._waiters.remove(ticket)
                except ValueError:
                    pass
                self._condition.notify_all()
                raise

        try:
            yield
        finally:
            with self._condition:
                if self._active_requests < 1:
                    raise RuntimeError(
                        "Provider request limiter accounting underflow"
                    )
                self._active_requests -= 1
                self._condition.notify_all()

    def snapshot(self) -> ProviderRequestLimiterSnapshot:
        with self._condition:
            return ProviderRequestLimiterSnapshot(
                max_concurrent_requests=self._max_concurrent_requests,
                active_requests=self._active_requests,
                waiting_requests=len(self._waiters),
            )


provider_request_limiter = ProviderRequestLimiter(
    settings.ai_provider_max_concurrent_requests
)


def post_json_limited(
    url: str,
    *,
    max_response_size_bytes: int,
    **request_kwargs: Any,
) -> Any:
    if (
        type(max_response_size_bytes) is not int
        or max_response_size_bytes < 1
    ):
        raise ValueError("Provider response size limit must be a positive integer")

    with provider_request_limiter.reserve():
        with httpx.stream("POST", url, **request_kwargs) as response:
            response.raise_for_status()
            return _read_limited_json(response, max_response_size_bytes)


def iter_openai_chat_completion_deltas(
    url: str,
    *,
    max_response_size_bytes: int,
    **request_kwargs: Any,
) -> Iterator[str]:
    """Yield text deltas from an OpenAI-compatible chat completion stream."""
    if (
        type(max_response_size_bytes) is not int
        or max_response_size_bytes < 1
    ):
        raise ValueError("Provider response size limit must be a positive integer")

    total_bytes = 0
    with provider_request_limiter.reserve():
        with httpx.stream("POST", url, **request_kwargs) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                total_bytes += len(line.encode("utf-8"))
                if total_bytes > max_response_size_bytes:
                    raise ProviderResponseTooLargeError(
                        "AI provider response exceeded the configured size limit"
                    )
                if line.startswith("data:"):
                    payload = line[5:].strip()
                else:
                    continue
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        break
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                if not isinstance(delta, dict):
                    continue
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content


def _read_limited_json(
    response: httpx.Response,
    max_response_size_bytes: int,
) -> Any:
    declared_size = _declared_content_length(response)
    if declared_size is not None and declared_size > max_response_size_bytes:
        raise ProviderResponseTooLargeError(
            "AI provider response exceeded the configured size limit"
        )

    body = bytearray()
    for chunk in response.iter_bytes(
        chunk_size=PROVIDER_RESPONSE_READ_CHUNK_BYTES,
    ):
        if len(chunk) > max_response_size_bytes - len(body):
            raise ProviderResponseTooLargeError(
                "AI provider response exceeded the configured size limit"
            )
        body.extend(chunk)
    return json.loads(body)


def _declared_content_length(response: httpx.Response) -> int | None:
    raw_value = response.headers.get("content-length")
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None
