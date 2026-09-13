import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ai import http_client
from app.ai.http_client import ProviderRequestLimiter, post_json_limited


class BlockingResponse:
    def __init__(
        self,
        release: threading.Event,
        state: dict[str, int],
        state_lock: threading.Lock,
    ) -> None:
        self.release = release
        self.state = state
        self.state_lock = state_lock
        self.headers = {}

    def __enter__(self):
        with self.state_lock:
            self.state["active"] += 1
            self.state["peak"] = max(
                self.state["peak"],
                self.state["active"],
            )
            self.state["entered"] += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        with self.state_lock:
            self.state["active"] -= 1

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int):
        if not self.release.wait(timeout=5):
            raise TimeoutError("test response was not released")
        yield b"{}"


class FailingResponse:
    headers = {}

    def __init__(self) -> None:
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.exited = True

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int):
        raise RuntimeError("response stream failed")
        yield b""


def _wait_until(predicate, timeout_seconds: float = 5) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def test_provider_limiter_caps_parallel_http_requests(monkeypatch) -> None:
    limiter = ProviderRequestLimiter(2)
    release = threading.Event()
    state_lock = threading.Lock()
    state = {"active": 0, "peak": 0, "entered": 0}
    monkeypatch.setattr(http_client, "provider_request_limiter", limiter)
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: BlockingResponse(
            release,
            state,
            state_lock,
        ),
    )

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(
                post_json_limited,
                "https://example.test/data",
                max_response_size_bytes=1024,
            )
            for _ in range(6)
        ]
        _wait_until(
            lambda: (
                limiter.snapshot().active_requests == 2
                and limiter.snapshot().waiting_requests == 4
            )
        )
        with state_lock:
            assert state == {"active": 2, "peak": 2, "entered": 2}
        release.set()
        assert [future.result(timeout=5) for future in futures] == [{}] * 6

    assert state == {"active": 0, "peak": 2, "entered": 6}
    assert limiter.snapshot().active_requests == 0
    assert limiter.snapshot().waiting_requests == 0


def test_provider_limiter_releases_slot_after_response_failure(
    monkeypatch,
) -> None:
    limiter = ProviderRequestLimiter(1)
    failed_response = FailingResponse()
    monkeypatch.setattr(http_client, "provider_request_limiter", limiter)
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: failed_response,
    )

    with pytest.raises(RuntimeError, match="response stream failed"):
        post_json_limited(
            "https://example.test/data",
            max_response_size_bytes=1024,
        )

    assert failed_response.exited is True
    assert limiter.snapshot().active_requests == 0
    assert limiter.snapshot().waiting_requests == 0

    release = threading.Event()
    release.set()
    state_lock = threading.Lock()
    state = {"active": 0, "peak": 0, "entered": 0}
    monkeypatch.setattr(
        http_client.httpx,
        "stream",
        lambda *args, **kwargs: BlockingResponse(
            release,
            state,
            state_lock,
        ),
    )

    assert post_json_limited(
        "https://example.test/data",
        max_response_size_bytes=1024,
    ) == {}
    assert state == {"active": 0, "peak": 1, "entered": 1}


def test_provider_limiter_grants_waiters_in_arrival_order() -> None:
    limiter = ProviderRequestLimiter(1)
    acquired: list[int] = []
    threads: list[threading.Thread] = []

    def wait_for_slot(index: int) -> None:
        with limiter.reserve():
            acquired.append(index)

    with limiter.reserve():
        for index in range(3):
            thread = threading.Thread(target=wait_for_slot, args=(index,))
            thread.start()
            threads.append(thread)
            _wait_until(
                lambda expected=index + 1: (
                    limiter.snapshot().waiting_requests == expected
                )
            )

    for thread in threads:
        thread.join(timeout=5)
        assert thread.is_alive() is False

    assert acquired == [0, 1, 2]
    assert limiter.snapshot().active_requests == 0
    assert limiter.snapshot().waiting_requests == 0


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_provider_concurrency_limit_is_rejected(limit) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ProviderRequestLimiter(limit)
