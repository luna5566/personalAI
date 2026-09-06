import asyncio
import threading

from app.workers import storage_deletion


def test_schedule_storage_deletion_batch_deduplicates_active_worker(
    monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def process_batch():
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(
        storage_deletion.storage_deletion_service,
        "process_storage_deletion_batch",
        process_batch,
    )

    async def run_test():
        registry = storage_deletion.StorageDeletionTaskRegistry()
        first = storage_deletion.schedule_storage_deletion_batch(registry)
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        second = storage_deletion.schedule_storage_deletion_batch(registry)

        assert len(first) == 1
        assert second == []
        assert registry.active_count == 1

        release.set()
        assert await registry.wait_for_completion(1) is True

    asyncio.run(run_test())


def test_periodic_storage_deletion_loop_stops_on_cancellation(monkeypatch) -> None:
    monkeypatch.setattr(
        storage_deletion.settings,
        "storage_deletion_interval_seconds",
        0.01,
    )
    calls = []

    def schedule(registry, state=None):
        calls.append((registry, state))
        return []

    monkeypatch.setattr(
        storage_deletion,
        "schedule_storage_deletion_batch",
        schedule,
    )

    async def run_test():
        registry = storage_deletion.StorageDeletionTaskRegistry()
        task = asyncio.create_task(
            storage_deletion.run_storage_deletion_loop(registry)
        )
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.005)
        assert calls
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled() is True
        assert calls == [(registry, None)]

    asyncio.run(run_test())


def test_storage_deletion_state_keeps_failure_until_a_retry_is_claimed() -> None:
    state = storage_deletion.StorageDeletionState()
    state.record_started()
    state.record_result(
        storage_deletion.storage_deletion_service.StorageDeletionBatchResult(
            claimed=1,
            completed=0,
            failed=1,
        )
    )

    state.record_started()
    state.record_result(
        storage_deletion.storage_deletion_service.StorageDeletionBatchResult(
            claimed=0,
            completed=0,
            failed=0,
        )
    )

    assert state.snapshot().last_failed == 1

    state.record_started()
    state.record_result(
        storage_deletion.storage_deletion_service.StorageDeletionBatchResult(
            claimed=1,
            completed=1,
            failed=0,
        )
    )

    snapshot = state.snapshot()
    assert snapshot.last_claimed == 1
    assert snapshot.last_completed == 1
    assert snapshot.last_failed == 0


def test_storage_deletion_wakeup_interrupts_periodic_wait() -> None:
    async def run_test():
        wakeup = storage_deletion.StorageDeletionWakeup()
        started = asyncio.Event()

        async def wait_for_signal():
            started.set()
            await wakeup.wait(10)

        waiter = asyncio.create_task(wait_for_signal())
        await started.wait()
        wakeup.notify()
        await asyncio.wait_for(waiter, timeout=1)

    asyncio.run(run_test())
