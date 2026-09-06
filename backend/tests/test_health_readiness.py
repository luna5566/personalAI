from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Response, status

from app.api.routes import health
from app.core.database import DatabasePoolSnapshot
from app.workers.job_recovery import JobRecoveryState
from app.services.storage_deletion_service import StorageDeletionBatchResult
from app.services.storage_deletion_service import StorageDeletionQueueSnapshot
from app.workers.storage_deletion import StorageDeletionState


class ReadySession:
    def __init__(self, values):
        self.values = iter(values)
        self.executions = []
        self.scalar_statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return next(self.values)

    def execute(self, statement, parameters=None):
        self.executions.append((statement, parameters))
        return None


@pytest.fixture(autouse=True)
def available_database_pool(monkeypatch):
    monkeypatch.setattr(
        health,
        "database_pool_snapshot",
        lambda: DatabasePoolSnapshot(
            pool_size=5,
            max_overflow=10,
            capacity=15,
            checked_in=1,
            checked_out=2,
            overflow=0,
            utilization_percent=13.3,
            saturated=False,
        ),
    )
    monkeypatch.setattr(
        health.storage_deletion_service,
        "storage_deletion_queue_snapshot",
        lambda db: queue_snapshot(),
    )


def queue_snapshot(
    *,
    pending: int = 0,
    failed: int = 0,
    abandoned: int = 0,
    active_leases: int = 0,
    eligible: int = 0,
) -> StorageDeletionQueueSnapshot:
    return StorageDeletionQueueSnapshot(
        pending=pending,
        failed=failed,
        abandoned=abandoned,
        active_leases=active_leases,
        eligible=eligible,
        oldest_created_at=None,
        earliest_next_attempt_at=None,
    )


def recovery_request(
    *,
    failures: int = 0,
    stopped: bool = False,
    storage_failed: bool = False,
    storage_stopped: bool = False,
):
    recovery_state = JobRecoveryState()
    recovery_state.record_scan_started()
    recovery_state.record_success()
    for _ in range(failures):
        recovery_state.record_scan_started()
        recovery_state.record_failure()
    recovery_task = SimpleNamespace(done=lambda: stopped)
    storage_deletion_state = StorageDeletionState()
    storage_deletion_state.record_started()
    storage_deletion_state.record_result(
        StorageDeletionBatchResult(
            claimed=1 if storage_failed else 0,
            completed=0,
            failed=1 if storage_failed else 0,
        )
    )
    storage_deletion_task = SimpleNamespace(done=lambda: storage_stopped)
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                job_recovery_state=recovery_state,
                job_recovery_loop_task=recovery_task,
                storage_deletion_state=storage_deletion_state,
                storage_deletion_loop_task=storage_deletion_task,
            )
        )
    )


def test_readiness_requires_database_vector_extension_and_index(monkeypatch) -> None:
    session = ReadySession([1, True, True])
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: session,
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "ready"
    assert result["database"] == "ready"
    assert result["database_connect_timeout_seconds"] == 5
    assert result["database_pool_timeout_seconds"] == 10
    assert result["database_statement_timeout_seconds"] == 30
    assert result["database_health_statement_timeout_seconds"] == 2
    assert result["hnsw_iterative_scan"] == "strict_order"
    assert result["hnsw_ef_search"] == 100
    assert result["hnsw_max_scan_tuples"] == 20000
    assert result["database_pool_size"] == 5
    assert result["database_pool_max_overflow"] == 10
    assert result["database_pool_capacity"] == 15
    assert result["database_pool_checked_in"] == 1
    assert result["database_pool_checked_out"] == 2
    assert result["database_pool_overflow"] == 0
    assert result["database_pool_utilization_percent"] == 13.3
    assert result["database_pool_saturated"] is False
    assert result["ai_provider_max_response_size_bytes"] == 8 * 1024 * 1024
    assert result["ai_provider_max_concurrent_requests"] == 8
    assert result["ai_provider_active_requests"] == 0
    assert result["ai_provider_waiting_requests"] == 0
    assert result["vector"] == "ready"
    assert result["index"] == "ready"
    assert result["job_recovery"] == "ready"
    assert result["job_recovery_reason"] is None
    assert result["job_recovery_last_scan_at"] is not None
    assert result["job_recovery_last_success_at"] is not None
    assert result["job_recovery_scan_started_at"] is None
    assert result["job_recovery_last_scan_duration_ms"] is not None
    assert result["job_recovery_consecutive_failures"] == 0
    assert result["job_recovery_last_dispatched_jobs"] == 0
    assert result["job_recovery_active_workers"] == 0
    assert result["job_recovery_max_active_workers"] == 50
    assert result["job_worker_occupied_slots"] == 0
    assert result["job_worker_waiting_tasks"] == 0
    assert result["job_worker_max_active_workers"] == 50
    assert result["job_recovery_scan_stale_after_seconds"] == 30
    assert result["job_recovery_statement_timeout_seconds"] == 30
    assert result["job_recovery_freshness_timeout_seconds"] == 180
    assert result["storage_deletion"] == "ready"
    assert result["storage_deletion_reason"] is None
    assert result["storage_deletion_last_success_at"] is not None
    assert result["storage_deletion_last_failed"] == 0
    assert result["storage_deletion_queue_pending"] == 0
    assert result["storage_deletion_queue_failed"] == 0
    assert result["storage_deletion_queue_abandoned"] == 0
    assert result["storage_deletion_queue_active_leases"] == 0
    assert result["storage_deletion_queue_eligible"] == 0
    assert result["storage_deletion_queue_oldest_created_at"] is None
    assert result["storage_deletion_queue_earliest_next_attempt_at"] is None
    assert result["storage_deletion_batch_size"] == 50
    assert result["storage_deletion_interval_seconds"] == 60
    assert result["storage_deletion_lease_seconds"] == 300
    assert result["storage_deletion_statement_timeout_seconds"] == 30
    assert result["storage_deletion_freshness_timeout_seconds"] == 600
    assert len(session.executions) == 1
    assert "set_config('statement_timeout'" in str(session.executions[0][0])
    assert session.executions[0][1] == {"timeout_ms": "2000"}
    assert "extversion" in str(session.scalar_statements[1])
    assert response.status_code == status.HTTP_200_OK


def test_capabilities_exposes_ai_provider_response_limit(monkeypatch) -> None:
    monkeypatch.setattr(health, "_hnsw_index_status", lambda: "present")

    result = health.capabilities()

    assert result["ai_provider"] == {
        "max_response_size_bytes": (
            health.settings.ai_provider_max_response_size_bytes
        ),
        "max_concurrent_requests": 8,
        "active_requests": 0,
        "waiting_requests": 0,
    }


def test_readiness_fails_fast_when_database_pool_is_saturated(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "database_pool_snapshot",
        lambda: DatabasePoolSnapshot(
            pool_size=1,
            max_overflow=0,
            capacity=1,
            checked_in=0,
            checked_out=1,
            overflow=0,
            utilization_percent=100.0,
            saturated=True,
        ),
    )

    def unexpected_session():
        raise AssertionError("saturated readiness must not wait for a connection")

    monkeypatch.setattr(health, "SessionLocal", unexpected_session)
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["database"] == "pool_saturated"
    assert result["vector"] == "unknown"
    assert result["index"] == "unknown"
    assert result["database_pool_capacity"] == 1
    assert result["database_pool_checked_out"] == 1
    assert result["database_pool_utilization_percent"] == 100.0
    assert result["database_pool_saturated"] is True
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_when_index_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, False]),
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["index"] == "missing"
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_requires_pgvector_iterative_scan_support(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, False, True]),
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["vector"] == "missing"
    assert result["index"] == "ready"
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_hides_database_errors(monkeypatch) -> None:
    def unavailable_session():
        raise RuntimeError("database credentials leaked here")

    monkeypatch.setattr(health, "SessionLocal", unavailable_session)
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["database"] == "unavailable"
    assert result["vector"] == "unknown"
    assert result["index"] == "unknown"
    assert result["job_recovery"] == "ready"
    assert "credentials" not in str(result)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_hides_health_timeout_setup_errors(monkeypatch) -> None:
    class TimeoutSession(ReadySession):
        def execute(self, statement, parameters=None):
            raise RuntimeError("database host and credentials leaked here")

    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: TimeoutSession([1, True, True]),
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["database"] == "unavailable"
    assert result["vector"] == "unknown"
    assert result["index"] == "unknown"
    assert "credentials" not in str(result)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_hides_storage_queue_snapshot_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )

    def fail_queue_snapshot(db):
        raise RuntimeError("storage database credentials leaked here")

    monkeypatch.setattr(
        health.storage_deletion_service,
        "storage_deletion_queue_snapshot",
        fail_queue_snapshot,
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["database"] == "unavailable"
    assert result["storage_deletion_queue_pending"] is None
    assert "credentials" not in str(result)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_capability_index_check_uses_health_statement_timeout(monkeypatch) -> None:
    session = ReadySession([True])
    monkeypatch.setattr(health, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        health.settings,
        "database_health_statement_timeout_seconds",
        1.25,
    )

    assert health._hnsw_index_status() == "present"
    assert len(session.executions) == 1
    assert session.executions[0][1] == {"timeout_ms": "1250"}
    index_sql = str(session.scalar_statements[0])
    assert "pg_index" in index_sql
    assert "access_method.amname = 'hnsw'" in index_sql
    assert "index_metadata.indisready" in index_sql
    assert "index_metadata.indisvalid" in index_sql
    assert "index_metadata.indislive" in index_sql
    assert "indexed_column.attname = 'embedding'" in index_sql
    assert "vector(1536)" in index_sql
    assert "operator_class.opcname = 'vector_l2_ops'" in index_sql
    assert "index_relation.reloptions" in index_sql
    assert "m=16" in index_sql
    assert "ef_construction=64" in index_sql


def test_readiness_returns_503_when_recovery_is_degraded(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    response = Response()

    result = health.readiness_check(
        recovery_request(failures=2),
        response,
    )

    assert result["status"] == "not_ready"
    assert result["job_recovery"] == "degraded"
    assert result["job_recovery_reason"] == "scan_failed"
    assert result["job_recovery_consecutive_failures"] == 2
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_when_recovery_loop_stopped(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    response = Response()

    result = health.readiness_check(
        recovery_request(stopped=True),
        response,
    )

    assert result["status"] == "not_ready"
    assert result["job_recovery"] == "stopped"
    assert result["job_recovery_reason"] == "supervisor_stopped"
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_when_storage_deletion_failed(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    monkeypatch.setattr(
        health.storage_deletion_service,
        "storage_deletion_queue_snapshot",
        lambda db: queue_snapshot(pending=1),
    )
    response = Response()

    result = health.readiness_check(
        recovery_request(storage_failed=True),
        response,
    )

    assert result["status"] == "not_ready"
    assert result["storage_deletion"] == "degraded"
    assert result["storage_deletion_reason"] == "deletion_failed"
    assert result["storage_deletion_last_claimed"] == 1
    assert result["storage_deletion_last_failed"] == 1
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_for_persistent_storage_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    monkeypatch.setattr(
        health.storage_deletion_service,
        "storage_deletion_queue_snapshot",
        lambda db: queue_snapshot(pending=1, failed=1),
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["storage_deletion"] == "degraded"
    assert result["storage_deletion_reason"] == "persistent_deletion_failed"
    assert result["storage_deletion_queue_pending"] == 1
    assert result["storage_deletion_queue_failed"] == 1
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_for_abandoned_storage_lease(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    monkeypatch.setattr(
        health.storage_deletion_service,
        "storage_deletion_queue_snapshot",
        lambda db: queue_snapshot(pending=1, abandoned=1, eligible=1),
    )
    response = Response()

    result = health.readiness_check(recovery_request(), response)

    assert result["status"] == "not_ready"
    assert result["storage_deletion_reason"] == "abandoned_deletion_lease"
    assert result["storage_deletion_queue_abandoned"] == 1
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_clears_stale_local_failure_after_global_success(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    response = Response()

    result = health.readiness_check(
        recovery_request(storage_failed=True),
        response,
    )

    assert result["status"] == "ready"
    assert result["storage_deletion"] == "ready"
    assert result["storage_deletion_reason"] is None
    assert result["storage_deletion_last_failed"] == 1
    assert result["storage_deletion_queue_pending"] == 0
    assert response.status_code == status.HTTP_200_OK


def test_readiness_returns_503_when_storage_deletion_loop_stopped(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    response = Response()

    result = health.readiness_check(
        recovery_request(storage_stopped=True),
        response,
    )

    assert result["status"] == "not_ready"
    assert result["storage_deletion"] == "stopped"
    assert result["storage_deletion_reason"] == "supervisor_stopped"
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_when_recovery_scan_is_overdue(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    monkeypatch.setattr(
        health.settings,
        "job_recovery_scan_stale_after_seconds",
        5,
    )
    request = recovery_request()
    recovery_state = request.app.state.job_recovery_state
    recovery_state.record_scan_started()
    recovery_state._scan_started_at = datetime.now(timezone.utc) - timedelta(
        seconds=6
    )
    response = Response()

    result = health.readiness_check(request, response)

    assert result["status"] == "not_ready"
    assert result["job_recovery"] == "degraded"
    assert result["job_recovery_reason"] == "scan_overdue"
    assert result["job_recovery_scan_started_at"] is not None
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_returns_503_when_recovery_success_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    monkeypatch.setattr(health.settings, "job_recovery_interval_seconds", 10)
    monkeypatch.setattr(
        health.settings,
        "job_recovery_scan_stale_after_seconds",
        5,
    )
    request = recovery_request()
    recovery_state = request.app.state.job_recovery_state
    recovery_state._last_success_at = datetime.now(timezone.utc) - timedelta(
        seconds=31
    )
    response = Response()

    result = health.readiness_check(request, response)

    assert result["status"] == "not_ready"
    assert result["job_recovery"] == "degraded"
    assert result["job_recovery_reason"] == "success_stale"
    assert result["job_recovery_freshness_timeout_seconds"] == 30
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_readiness_requires_recovery_state(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "SessionLocal",
        lambda: ReadySession([1, True, True]),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                job_recovery_loop_task=SimpleNamespace(done=lambda: False),
            )
        )
    )
    response = Response()

    result = health.readiness_check(request, response)

    assert result["status"] == "not_ready"
    assert result["job_recovery"] == "degraded"
    assert result["job_recovery_reason"] == "state_unavailable"
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
