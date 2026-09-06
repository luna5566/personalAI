import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.job import JobStatus, JobType
from app import main as app_main
from app.storage import storage_service
from app.workers import document_pipeline, job_recovery


def test_recovered_document_job_is_dispatched(monkeypatch) -> None:
    calls = []
    run_token = uuid4()
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        job_type=JobType.INDEX_DOCUMENT.value,
        run_token=run_token,
    )
    monkeypatch.setattr(
        job_recovery,
        "process_document",
        lambda job_id, document_id, run_token: calls.append(
            (job_id, document_id, run_token)
        ),
    )

    job_recovery.run_recoverable_job(job)

    assert calls == [(job.id, job.document_id, run_token)]


def test_recovered_embedding_job_is_dispatched(monkeypatch) -> None:
    calls = []
    run_token = uuid4()
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        run_token=run_token,
    )
    monkeypatch.setattr(
        job_recovery,
        "rebuild_embeddings",
        lambda job_id, user_id, run_token: calls.append(
            (job_id, user_id, run_token)
        ),
    )

    job_recovery.run_recoverable_job(job)

    assert calls == [(job.id, job.user_id, run_token)]


def test_recovered_global_embedding_job_is_dispatched(monkeypatch) -> None:
    calls = []
    run_token = uuid4()
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_ALL_EMBEDDINGS.value,
        run_token=run_token,
    )
    monkeypatch.setattr(
        job_recovery,
        "rebuild_embeddings",
        lambda job_id, user_id, run_token: calls.append(
            (job_id, user_id, run_token)
        ),
    )

    job_recovery.run_recoverable_job(job)

    assert calls == [(job.id, None, run_token)]


def test_unknown_recovered_job_type_persists_only_public_error(monkeypatch) -> None:
    stored_job = SimpleNamespace(id=uuid4(), status=JobStatus.RUNNING.value)
    failed_jobs = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return stored_job

    monkeypatch.setattr(job_recovery, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        job_recovery.job_service,
        "fail_active_job",
        lambda *args, **kwargs: failed_jobs.append(kwargs),
    )
    internal_job_type = "private/path?api_key=secret"
    job = job_recovery.RecoverableJob(
        id=stored_job.id,
        user_id=uuid4(),
        document_id=None,
        job_type=internal_job_type,
        run_token=uuid4(),
    )

    job_recovery.run_recoverable_job(job)

    assert failed_jobs == [
        {
            "message": "无法恢复未知任务",
            "error_message": "任务类型不受支持，无法自动恢复",
        }
    ]
    assert internal_job_type not in failed_jobs[0]["error_message"]


def test_document_job_is_failed_when_source_document_was_deleted(monkeypatch) -> None:
    job = SimpleNamespace(id=uuid4(), status=JobStatus.PENDING.value)
    updates = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return job

        def rollback(self):
            return None

    monkeypatch.setattr(document_pipeline, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_cancel_requested",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: updates.append({"action": "claim"}),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: updates.append({"action": "fail", **kwargs}),
    )

    document_pipeline.process_document(job.id, uuid4())

    assert [update["action"] for update in updates] == ["claim", "fail"]
    assert updates[1]["message"] == "处理失败"
    assert "资料已删除" in updates[1]["error_message"]


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (
            storage_service.StorageBackendChangedError(
                "资料存储配置与上传时不一致，请恢复原存储配置后重试"
            ),
            "资料存储配置与上传时不一致，请恢复原存储配置后重试",
        ),
        (
            RuntimeError(
                "C:\\private\\document.pdf https://internal.example api_key=secret"
            ),
            "资料解析失败，请确认文件有效后重试",
        ),
    ],
)
def test_document_job_persists_only_public_processing_failure(
    monkeypatch,
    error,
    expected_error,
) -> None:
    job = SimpleNamespace(id=uuid4(), status=JobStatus.PENDING.value)
    document = SimpleNamespace(
        id=uuid4(),
        status="uploaded",
        error_message=None,
    )
    failed_jobs = []
    chunk_calls = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return job

        def add(self, value):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    class FakeHeartbeat:
        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(document_pipeline, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: document,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "JobHeartbeat",
        lambda *args: FakeHeartbeat(),
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_cancel_requested",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "raise_if_job_stopped",
        lambda *args: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "start_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        document_pipeline.job_service,
        "fail_active_job",
        lambda *args, **kwargs: failed_jobs.append(kwargs),
    )
    monkeypatch.setattr(
        document_pipeline.parsing_service,
        "parse_document",
        lambda value: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        document_pipeline.chunking_service,
        "recreate_document_chunks",
        lambda *args: chunk_calls.append(True),
    )

    document_pipeline.process_document(job.id, document.id)

    assert chunk_calls == []
    assert document.status == "failed"
    assert document.error_message == expected_error
    assert "private" not in document.error_message
    assert "api_key" not in document.error_message
    assert failed_jobs == [
        {
            "message": "处理失败",
            "error_message": expected_error,
        }
    ]


def test_finished_document_job_is_not_processed_again(monkeypatch) -> None:
    job = SimpleNamespace(id=uuid4(), status=JobStatus.SUCCESS.value)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, model, object_id):
            return job

    parse_document = []
    monkeypatch.setattr(document_pipeline, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        document_pipeline.document_service,
        "get_document_by_id",
        lambda *args: SimpleNamespace(id=uuid4()),
    )
    monkeypatch.setattr(
        document_pipeline.parsing_service,
        "parse_document",
        lambda document: parse_document.append(document),
    )

    document_pipeline.process_document(job.id, uuid4())

    assert parse_document == []


def test_schedule_can_skip_maintenance(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        job_recovery.maintenance_service,
        "purge_expired_data",
        lambda: calls.append("maintenance"),
    )
    monkeypatch.setattr(
        job_recovery,
        "claim_recoverable_jobs",
        lambda *, limit: calls.append("claim") or [],
    )

    async def run_schedule():
        assert await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False
        ) == []

    asyncio.run(run_schedule())

    assert calls == ["claim"]


def test_recovery_state_tracks_scan_duration(monkeypatch) -> None:
    monotonic_values = iter([10.0, 10.125])
    monkeypatch.setattr(
        job_recovery,
        "monotonic",
        lambda: next(monotonic_values),
    )
    state = job_recovery.JobRecoveryState()

    state.record_scan_started()
    started = state.snapshot()
    assert started.scan_started_at is not None
    assert started.last_scan_duration_ms is None

    state.record_success()
    completed = state.snapshot()
    assert completed.scan_started_at is None
    assert completed.last_scan_duration_ms == 125


def test_recovery_claim_does_not_block_event_loop(monkeypatch) -> None:
    claim_started = threading.Event()
    release_claim = threading.Event()

    def claim(*, limit):
        claim_started.set()
        assert release_claim.wait(timeout=1)
        return []

    monkeypatch.setattr(job_recovery, "claim_recoverable_jobs", claim)

    async def run_schedule():
        schedule_task = asyncio.create_task(
            job_recovery.schedule_recoverable_jobs(run_maintenance=False)
        )
        try:
            for _ in range(100):
                if claim_started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert claim_started.is_set()
            assert schedule_task.done() is False
        finally:
            release_claim.set()
        assert await schedule_task == []

    asyncio.run(run_schedule())


def test_maintenance_does_not_block_event_loop(monkeypatch) -> None:
    maintenance_started = threading.Event()
    release_maintenance = threading.Event()

    def maintain():
        maintenance_started.set()
        assert release_maintenance.wait(timeout=1)

    monkeypatch.setattr(
        job_recovery.maintenance_service,
        "purge_expired_data",
        maintain,
    )
    monkeypatch.setattr(
        job_recovery,
        "claim_recoverable_jobs",
        lambda *, limit: [],
    )

    async def run_schedule():
        schedule_task = asyncio.create_task(
            job_recovery.schedule_recoverable_jobs()
        )
        try:
            for _ in range(100):
                if maintenance_started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert maintenance_started.is_set()
            assert schedule_task.done() is False
        finally:
            release_maintenance.set()
        assert await schedule_task == []

    asyncio.run(run_schedule())


def test_cancelled_scan_dispatches_claimed_jobs_before_stopping(monkeypatch) -> None:
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        run_token=uuid4(),
    )
    claim_started = threading.Event()
    release_claim = threading.Event()
    worker_started = threading.Event()
    state = job_recovery.JobRecoveryState()
    task_registry = job_recovery.JobRecoveryTaskRegistry()

    def claim(*, limit):
        claim_started.set()
        assert release_claim.wait(timeout=1)
        return [job]

    monkeypatch.setattr(job_recovery, "claim_recoverable_jobs", claim)
    monkeypatch.setattr(
        job_recovery,
        "run_recoverable_job",
        lambda value: worker_started.set(),
    )

    async def run_cancelled_scan():
        schedule_task = asyncio.create_task(
            job_recovery.schedule_recoverable_jobs(
                run_maintenance=False,
                state=state,
                task_registry=task_registry,
            )
        )
        for _ in range(100):
            if claim_started.is_set():
                break
            await asyncio.sleep(0.001)
        assert claim_started.is_set()

        schedule_task.cancel()
        await asyncio.sleep(0)
        assert schedule_task.done() is False

        release_claim.set()
        with pytest.raises(asyncio.CancelledError):
            await schedule_task

        assert task_registry.active_count == 1
        assert await task_registry.wait_for_completion(1) is True
        await asyncio.sleep(0)
        assert worker_started.is_set()
        assert task_registry.active_count == 0
        assert state.snapshot().active_workers == 0

    asyncio.run(run_cancelled_scan())


def test_periodic_recovery_continues_after_scan_failure(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_interval_seconds",
        0.01,
    )

    async def run_loop():
        recovered = asyncio.Event()
        recovery_state = job_recovery.JobRecoveryState()
        task_registry = job_recovery.JobRecoveryTaskRegistry()

        async def schedule(*, run_maintenance, state, task_registry):
            calls.append(run_maintenance)
            assert task_registry is not None
            if len(calls) == 1:
                raise RuntimeError("database unavailable")
            recovered.set()
            return []

        monkeypatch.setattr(job_recovery, "schedule_recoverable_jobs", schedule)
        task = asyncio.create_task(
            job_recovery.run_recovery_loop(recovery_state, task_registry)
        )
        await asyncio.wait_for(recovered.wait(), timeout=1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        snapshot = recovery_state.snapshot()
        assert snapshot.consecutive_failures == 0
        assert snapshot.last_success_at is not None
        assert snapshot.scan_started_at is None
        assert snapshot.last_scan_duration_ms is not None

    asyncio.run(run_loop())

    assert calls == [True, True]


def test_periodic_recovery_clears_scan_state_when_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_interval_seconds",
        0.01,
    )

    async def run_loop():
        scan_started = asyncio.Event()
        recovery_state = job_recovery.JobRecoveryState()

        async def schedule(*, run_maintenance, state, task_registry):
            assert run_maintenance is True
            scan_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(job_recovery, "schedule_recoverable_jobs", schedule)
        task = asyncio.create_task(job_recovery.run_recovery_loop(recovery_state))
        await asyncio.wait_for(scan_started.wait(), timeout=1)
        assert recovery_state.snapshot().scan_started_at is not None

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert recovery_state.snapshot().scan_started_at is None

    asyncio.run(run_loop())


def test_lifespan_cancels_recovery_loop(monkeypatch) -> None:
    events = []

    class FakeTaskRegistry:
        async def wait_for_completion(self, timeout_seconds):
            events.append(("workers_waited", timeout_seconds))
            return True

    task_registry = FakeTaskRegistry()
    storage_deletion_registry = FakeTaskRegistry()
    monkeypatch.setattr(
        app_main,
        "JobRecoveryTaskRegistry",
        lambda: task_registry,
    )
    monkeypatch.setattr(
        app_main,
        "StorageDeletionTaskRegistry",
        lambda: storage_deletion_registry,
    )
    monkeypatch.setattr(
        app_main.settings,
        "job_recovery_shutdown_timeout_seconds",
        0.25,
    )
    monkeypatch.setattr(
        app_main.settings,
        "storage_deletion_shutdown_timeout_seconds",
        0.5,
    )
    async def initial_schedule(*, state, task_registry):
        events.append("initial")
        return []

    monkeypatch.setattr(app_main, "schedule_recoverable_jobs", initial_schedule)

    async def recovery_loop(state, registry):
        events.append("loop_started")
        assert registry is task_registry
        assert state.snapshot().last_success_at is not None
        try:
            await asyncio.Event().wait()
        finally:
            events.append("loop_stopped")

    monkeypatch.setattr(app_main, "run_recovery_loop", recovery_loop)

    storage_states = []

    def initial_storage_schedule(registry, state):
        events.append("storage_initial")
        assert registry is storage_deletion_registry
        storage_states.append(state)
        return []

    monkeypatch.setattr(
        app_main,
        "schedule_storage_deletion_batch",
        initial_storage_schedule,
    )

    async def storage_deletion_loop(registry, state, wakeup):
        events.append("storage_loop_started")
        assert registry is storage_deletion_registry
        assert state is storage_states[0]
        assert isinstance(wakeup, app_main.StorageDeletionWakeup)
        try:
            await asyncio.Event().wait()
        finally:
            events.append("storage_loop_stopped")

    monkeypatch.setattr(
        app_main,
        "run_storage_deletion_loop",
        storage_deletion_loop,
    )

    async def run_lifespan():
        app = SimpleNamespace(state=SimpleNamespace())
        async with app_main.lifespan(app):
            await asyncio.sleep(0)
            assert app.state.recovered_job_tasks == []
            assert app.state.job_recovery_task_registry is task_registry
            assert app.state.job_recovery_loop_task.done() is False
            assert (
                app.state.storage_deletion_task_registry
                is storage_deletion_registry
            )
            assert app.state.storage_deletion_loop_task.done() is False
        assert app.state.job_recovery_loop_task.cancelled() is True
        assert app.state.storage_deletion_loop_task.cancelled() is True

    asyncio.run(run_lifespan())

    assert events == [
        "initial",
        "storage_initial",
        "loop_started",
        "storage_loop_started",
        "loop_stopped",
        "storage_loop_stopped",
        ("workers_waited", 0.25),
        ("workers_waited", 0.5),
    ]


def test_schedule_tracks_active_recovery_workers(monkeypatch) -> None:
    run_token = uuid4()
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        run_token=run_token,
    )
    state = job_recovery.JobRecoveryState()
    task_registry = job_recovery.JobRecoveryTaskRegistry()
    monkeypatch.setattr(
        job_recovery,
        "claim_recoverable_jobs",
        lambda *, limit: [job],
    )
    monkeypatch.setattr(
        job_recovery,
        "run_recoverable_job",
        lambda value: None,
    )

    async def run_schedule():
        tasks = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
            task_registry=task_registry,
        )
        scheduled = state.snapshot()
        assert scheduled.last_dispatched_jobs == 1
        assert scheduled.active_workers == 1
        assert task_registry.active_count == 1
        assert await task_registry.wait_for_completion(1) is True
        await asyncio.sleep(0)
        assert tasks[0].done() is True
        assert task_registry.active_count == 0

    asyncio.run(run_schedule())

    assert state.snapshot().active_workers == 0


def test_recovery_registry_cancels_workers_after_shutdown_timeout(monkeypatch) -> None:
    job = job_recovery.RecoverableJob(
        id=uuid4(),
        user_id=uuid4(),
        document_id=None,
        job_type=JobType.REBUILD_EMBEDDINGS.value,
        run_token=uuid4(),
    )
    state = job_recovery.JobRecoveryState()
    task_registry = job_recovery.JobRecoveryTaskRegistry()
    monkeypatch.setattr(job_recovery.settings, "job_recovery_batch_size", 1)
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_max_active_workers",
        1,
    )
    monkeypatch.setattr(
        job_recovery,
        "claim_recoverable_jobs",
        lambda *, limit: [job],
    )
    monkeypatch.setattr(
        job_recovery,
        "run_recoverable_job",
        lambda value: threading.Event().wait(timeout=0.05),
    )

    async def run_shutdown():
        tasks = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
            task_registry=task_registry,
        )
        assert state.snapshot().active_workers == 1
        assert task_registry.active_count == 1

        assert await task_registry.wait_for_completion(0) is False
        await asyncio.sleep(0)

        assert tasks[0].cancelled() is True
        assert state.snapshot().active_workers == 0
        assert task_registry.active_count == 0

    asyncio.run(run_shutdown())


def test_schedule_caps_recovery_workers_across_scans(monkeypatch) -> None:
    jobs = [
        job_recovery.RecoverableJob(
            id=uuid4(),
            user_id=uuid4(),
            document_id=None,
            job_type=JobType.REBUILD_EMBEDDINGS.value,
            run_token=uuid4(),
        )
        for _ in range(5)
    ]
    claim_limits = []
    gate = threading.Event()
    state = job_recovery.JobRecoveryState()
    monkeypatch.setattr(job_recovery.settings, "job_recovery_batch_size", 4)
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_max_active_workers",
        3,
    )

    def claim(*, limit):
        claim_limits.append(limit)
        count = min(limit, 2 if len(claim_limits) == 1 else len(jobs))
        claimed = jobs[:count]
        del jobs[:count]
        return claimed

    monkeypatch.setattr(job_recovery, "claim_recoverable_jobs", claim)
    monkeypatch.setattr(
        job_recovery,
        "run_recoverable_job",
        lambda value: gate.wait(timeout=2),
    )

    async def run_scans():
        first = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
        )
        assert len(first) == 2
        assert state.snapshot().active_workers == 2

        second = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
        )
        assert len(second) == 1
        assert state.snapshot().active_workers == 3

        saturated = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
        )
        assert saturated == []
        assert state.snapshot().last_dispatched_jobs == 0
        assert claim_limits == [3, 1]

        gate.set()
        await asyncio.gather(*first, *second)
        await asyncio.sleep(0)
        assert state.snapshot().active_workers == 0

        final = await job_recovery.schedule_recoverable_jobs(
            run_maintenance=False,
            state=state,
        )
        assert len(final) == 2
        assert state.snapshot().active_workers == 2
        await asyncio.gather(*final)
        await asyncio.sleep(0)

    asyncio.run(run_scans())

    assert claim_limits == [3, 1, 3]
    assert jobs == []
    assert state.snapshot().active_workers == 0


def test_schedule_releases_reserved_slots_after_claim_failure(monkeypatch) -> None:
    state = job_recovery.JobRecoveryState()
    monkeypatch.setattr(job_recovery.settings, "job_recovery_batch_size", 5)
    monkeypatch.setattr(
        job_recovery.settings,
        "job_recovery_max_active_workers",
        2,
    )

    def fail_claim(*, limit):
        assert limit == 2
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(job_recovery, "claim_recoverable_jobs", fail_claim)

    async def run_schedule():
        with pytest.raises(RuntimeError, match="database unavailable"):
            await job_recovery.schedule_recoverable_jobs(
                run_maintenance=False,
                state=state,
            )

    asyncio.run(run_schedule())

    snapshot = state.snapshot()
    assert snapshot.last_dispatched_jobs == 0
    assert snapshot.active_workers == 0
