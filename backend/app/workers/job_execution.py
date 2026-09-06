from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import threading
from typing import Any, TypeVar

from app.core.config import settings


ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class JobWorkerLimiterSnapshot:
    max_active_workers: int
    occupied_slots: int
    waiting_tasks: int


class JobWorkerPermit:
    def __init__(self, limiter: JobWorkerLimiter) -> None:
        self._limiter = limiter
        self._lock = threading.Lock()
        self._released = False
        self._started = False

    async def run(
        self,
        worker: Callable[..., ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> ResultT:
        with self._lock:
            if self._released or self._started:
                raise RuntimeError("job worker permit is no longer available")
            self._started = True

        def execute() -> ResultT:
            try:
                return worker(*args, **kwargs)
            finally:
                self.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(None, execute)
        except BaseException:
            self.release()
            raise
        return await future

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._limiter._release_slot()


class JobWorkerLimiter:
    def __init__(self, max_active_workers: int) -> None:
        if max_active_workers < 1:
            raise ValueError("max active job workers must be at least one")
        self._max_active_workers = max_active_workers
        self._lock = threading.Lock()
        self._occupied_slots = 0
        self._waiting_tasks = 0
        self._waiters: deque[
            tuple[asyncio.AbstractEventLoop, asyncio.Future[JobWorkerPermit]]
        ] = deque()

    async def acquire(self) -> JobWorkerPermit:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._occupied_slots < self._max_active_workers:
                self._occupied_slots += 1
                return JobWorkerPermit(self)
            waiter = loop.create_future()
            self._waiters.append((loop, waiter))
            self._waiting_tasks += 1

        try:
            return await waiter
        except asyncio.CancelledError:
            removed = False
            with self._lock:
                for queued in self._waiters:
                    if queued[1] is waiter:
                        self._waiters.remove(queued)
                        self._waiting_tasks = max(
                            self._waiting_tasks - 1,
                            0,
                        )
                        removed = True
                        break
            if removed:
                waiter.cancel()
            elif waiter.done() and not waiter.cancelled():
                waiter.result().release()
            raise

    def reserve_up_to(self, requested: int) -> list[JobWorkerPermit]:
        if requested < 0:
            raise ValueError("requested job worker slots cannot be negative")
        with self._lock:
            available = max(
                self._max_active_workers - self._occupied_slots,
                0,
            )
            reserved = min(requested, available)
            self._occupied_slots += reserved
        return [JobWorkerPermit(self) for _ in range(reserved)]

    async def run(
        self,
        worker: Callable[..., ResultT],
        *args: Any,
        **kwargs: Any,
    ) -> ResultT:
        permit = await self.acquire()
        return await permit.run(worker, *args, **kwargs)

    def snapshot(self) -> JobWorkerLimiterSnapshot:
        with self._lock:
            return JobWorkerLimiterSnapshot(
                max_active_workers=self._max_active_workers,
                occupied_slots=self._occupied_slots,
                waiting_tasks=self._waiting_tasks,
            )

    def _release_slot(self) -> None:
        waiter: tuple[
            asyncio.AbstractEventLoop,
            asyncio.Future[JobWorkerPermit],
        ] | None = None
        with self._lock:
            if self._occupied_slots < 1:
                raise RuntimeError("job worker slot accounting underflow")
            while self._waiters:
                candidate = self._waiters.popleft()
                self._waiting_tasks = max(self._waiting_tasks - 1, 0)
                if not candidate[1].cancelled():
                    waiter = candidate
                    break
            if waiter is None:
                self._occupied_slots -= 1
                return

        loop, future = waiter
        try:
            loop.call_soon_threadsafe(self._grant_waiter, future)
        except RuntimeError:
            self._release_slot()

    def _grant_waiter(
        self,
        future: asyncio.Future[JobWorkerPermit],
    ) -> None:
        if future.cancelled():
            self._release_slot()
            return
        try:
            future.set_result(JobWorkerPermit(self))
        except asyncio.InvalidStateError:
            self._release_slot()


job_worker_limiter = JobWorkerLimiter(
    settings.job_recovery_max_active_workers
)


async def run_job_with_worker_limit(
    worker: Callable[..., ResultT],
    *args: Any,
    **kwargs: Any,
) -> ResultT:
    return await job_worker_limiter.run(worker, *args, **kwargs)
