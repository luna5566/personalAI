from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from app.core.config import settings
from app.services import storage_deletion_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageDeletionSnapshot:
    last_run_at: datetime | None
    last_success_at: datetime | None
    batch_started_at: datetime | None
    last_batch_duration_ms: int | None
    consecutive_failures: int
    last_claimed: int
    last_completed: int
    last_failed: int


class StorageDeletionState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._batch_started_at: datetime | None = None
        self._batch_started_monotonic: float | None = None
        self._last_batch_duration_ms: int | None = None
        self._consecutive_failures = 0
        self._last_claimed = 0
        self._last_completed = 0
        self._last_failed = 0

    def record_started(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._batch_started_at = now
            self._batch_started_monotonic = monotonic()

    def record_result(
        self,
        result: storage_deletion_service.StorageDeletionBatchResult,
    ) -> None:
        now = datetime.now(UTC)
        with self._lock:
            first_result = self._last_run_at is None
            self._finish_batch()
            self._last_run_at = now
            self._last_success_at = now
            self._consecutive_failures = 0
            if result.claimed > 0 or first_result:
                self._last_claimed = result.claimed
                self._last_completed = result.completed
                self._last_failed = result.failed

    def record_failure(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._finish_batch()
            self._last_run_at = now
            self._consecutive_failures += 1

    def record_cancelled(self) -> None:
        with self._lock:
            self._batch_started_at = None
            self._batch_started_monotonic = None

    def snapshot(self) -> StorageDeletionSnapshot:
        with self._lock:
            return StorageDeletionSnapshot(
                last_run_at=self._last_run_at,
                last_success_at=self._last_success_at,
                batch_started_at=self._batch_started_at,
                last_batch_duration_ms=self._last_batch_duration_ms,
                consecutive_failures=self._consecutive_failures,
                last_claimed=self._last_claimed,
                last_completed=self._last_completed,
                last_failed=self._last_failed,
            )

    def _finish_batch(self) -> None:
        if self._batch_started_monotonic is not None:
            elapsed_ms = round(
                (monotonic() - self._batch_started_monotonic) * 1000
            )
            self._last_batch_duration_ms = max(elapsed_ms, 0)
        self._batch_started_at = None
        self._batch_started_monotonic = None


class StorageDeletionTaskRegistry:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def track(self, task: asyncio.Task[None]) -> None:
        self._idle.clear()
        self._tasks.add(task)
        task.add_done_callback(self._record_task_finished)

    async def wait_until_idle(self) -> None:
        await self._idle.wait()

    async def wait_for_completion(self, timeout_seconds: float) -> bool:
        tasks = set(self._tasks)
        if not tasks:
            return True

        _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        if not pending:
            return True

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return False

    def _record_task_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not self._tasks:
            self._idle.set()


class StorageDeletionWakeup:
    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()

    def notify(self) -> None:
        self._loop.call_soon_threadsafe(self._event.set)

    async def wait(self, timeout_seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self._event.wait(),
                timeout=timeout_seconds,
            )
        self._event.clear()


def schedule_storage_deletion_batch(
    task_registry: StorageDeletionTaskRegistry,
    state: StorageDeletionState | None = None,
) -> list[asyncio.Task[None]]:
    if task_registry.active_count > 0:
        return []

    if state is not None:
        state.record_started()
    task = asyncio.create_task(
        asyncio.to_thread(storage_deletion_service.process_storage_deletion_batch)
    )
    task.add_done_callback(
        lambda completed, deletion_state=state: _consume_task_result(
            completed,
            deletion_state,
        )
    )
    task_registry.track(task)
    return [task]


async def run_storage_deletion_loop(
    task_registry: StorageDeletionTaskRegistry,
    state: StorageDeletionState | None = None,
    wakeup: StorageDeletionWakeup | None = None,
) -> None:
    while True:
        if wakeup is None:
            await asyncio.sleep(settings.storage_deletion_interval_seconds)
        else:
            await wakeup.wait(settings.storage_deletion_interval_seconds)
        await task_registry.wait_until_idle()
        schedule_storage_deletion_batch(task_registry, state)


def _consume_task_result(
    task: asyncio.Task[storage_deletion_service.StorageDeletionBatchResult],
    state: StorageDeletionState | None = None,
) -> None:
    try:
        result = task.result()
    except asyncio.CancelledError:
        if state is not None:
            state.record_cancelled()
    except Exception:
        if state is not None:
            state.record_failure()
        logger.warning("Storage deletion worker failed", exc_info=True)
    else:
        if state is not None:
            state.record_result(result)
