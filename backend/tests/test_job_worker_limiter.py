import asyncio
import threading
from uuid import uuid4

import pytest

from app.models.job import JobType
from app.workers import job_recovery
from app.workers.job_execution import JobWorkerLimiter


async def _wait_until(predicate, attempts: int = 200) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition was not reached")


def test_job_worker_limiter_caps_actual_parallel_workers() -> None:
    limiter = JobWorkerLimiter(2)
    release_workers = threading.Event()
    state_lock = threading.Lock()
    active_workers = 0
    max_active_workers = 0

    def worker() -> None:
        nonlocal active_workers, max_active_workers
        with state_lock:
            active_workers += 1
            max_active_workers = max(max_active_workers, active_workers)
        release_workers.wait(timeout=2)
        with state_lock:
            active_workers -= 1

    async def run_scenario() -> None:
        tasks = [
            asyncio.create_task(limiter.run(worker))
            for _ in range(6)
        ]
        await _wait_until(
            lambda: limiter.snapshot().waiting_tasks == 4
        )
        snapshot = limiter.snapshot()
        assert snapshot.occupied_slots == 2
        assert snapshot.waiting_tasks == 4

        release_workers.set()
        await asyncio.gather(*tasks)

        assert limiter.snapshot().occupied_slots == 0
        assert limiter.snapshot().waiting_tasks == 0

    asyncio.run(run_scenario())

    assert max_active_workers == 2


def test_recovery_does_not_claim_while_background_worker_uses_capacity(
    monkeypatch,
) -> None:
    limiter = JobWorkerLimiter(1)
    state = job_recovery.JobRecoveryState()
    ordinary_started = threading.Event()
    release_ordinary = threading.Event()
    claim_limits = []
    recovered = []
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        run_token=uuid4(),
    )
    monkeypatch.setattr(job_recovery.settings, "job_recovery_batch_size", 5)
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_max_active_workers",
        5,
    )

    def ordinary_worker() -> None:
        ordinary_started.set()
        release_ordinary.wait(timeout=2)

    def claim(*, limit):
        claim_limits.append(limit)
        return [job]

    monkeypatch.setattr(job_recovery, "claim_recoverable_jobs", claim)
    monkeypatch.setattr(
        job_recovery,
        "run_recoverable_job",
        lambda value: recovered.append(value.id),
    )

    async def run_scenario() -> None:
        ordinary = asyncio.create_task(limiter.run(ordinary_worker))
        await _wait_until(ordinary_started.is_set)

        saturated = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
            worker_limiter=limiter,
        )
        assert saturated == []
        assert claim_limits == []
        assert state.snapshot().active_workers == 0
        assert limiter.snapshot().occupied_slots == 1

        release_ordinary.set()
        await ordinary

        tasks = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
            worker_limiter=limiter,
        )
        assert len(tasks) == 1
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)

        assert claim_limits == [1]
        assert recovered == [job.id]
        assert state.snapshot().active_workers == 0
        assert limiter.snapshot().occupied_slots == 0

    asyncio.run(run_scenario())


def test_cancelled_wrapper_retains_slot_until_worker_thread_finishes() -> None:
    limiter = JobWorkerLimiter(1)
    worker_started = threading.Event()
    release_worker = threading.Event()

    def worker() -> None:
        worker_started.set()
        release_worker.wait(timeout=2)

    async def run_scenario() -> None:
        task = asyncio.create_task(limiter.run(worker))
        await _wait_until(worker_started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert limiter.snapshot().occupied_slots == 1
        assert limiter.reserve_up_to(1) == []

        release_worker.set()
        await _wait_until(
            lambda: limiter.snapshot().occupied_slots == 0
        )

    asyncio.run(run_scenario())
