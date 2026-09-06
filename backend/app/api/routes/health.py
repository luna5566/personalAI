from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.ai.http_client import provider_request_limiter
from app.core.database import (
    SessionLocal,
    database_pool_snapshot,
    set_local_statement_timeout,
)
from app.core.config import (
    DATABASE_HNSW_EF_CONSTRUCTION,
    DATABASE_HNSW_M,
    DATABASE_VECTOR_DIMENSIONS,
    settings,
)
from app.services import storage_deletion_service
from app.workers.job_execution import job_worker_limiter
from app.workers.job_recovery import JobRecoveryState
from app.workers.storage_deletion import StorageDeletionState

router = APIRouter()
HNSW_INDEX_COMPATIBILITY_SQL = text(
    f"""
    SELECT EXISTS (
        SELECT 1
        FROM pg_class AS index_relation
        JOIN pg_namespace AS table_namespace
          ON table_namespace.nspname = current_schema()
        JOIN pg_class AS table_relation
          ON table_relation.relnamespace = table_namespace.oid
         AND table_relation.relname = 'chunk_embeddings'
        JOIN pg_index AS index_metadata
          ON index_metadata.indexrelid = index_relation.oid
         AND index_metadata.indrelid = table_relation.oid
        JOIN pg_am AS access_method
          ON access_method.oid = index_relation.relam
        JOIN pg_attribute AS indexed_column
          ON indexed_column.attrelid = table_relation.oid
         AND indexed_column.attnum = index_metadata.indkey[0]
        JOIN pg_opclass AS operator_class
          ON operator_class.oid = index_metadata.indclass[0]
        WHERE index_relation.relname = 'ix_chunk_embeddings_embedding_hnsw'
          AND index_relation.relnamespace = table_namespace.oid
          AND index_relation.relkind = 'i'
          AND access_method.amname = 'hnsw'
          AND index_metadata.indisready
          AND index_metadata.indisvalid
          AND index_metadata.indislive
          AND NOT index_metadata.indisunique
          AND index_metadata.indnatts = 1
          AND index_metadata.indnkeyatts = 1
          AND index_metadata.indexprs IS NULL
          AND index_metadata.indpred IS NULL
          AND indexed_column.attname = 'embedding'
          AND format_type(
              indexed_column.atttypid,
              indexed_column.atttypmod
          ) = 'vector({DATABASE_VECTOR_DIMENSIONS})'
          AND operator_class.opcname = 'vector_l2_ops'
          AND COALESCE(
              index_relation.reloptions,
              ARRAY[]::text[]
          ) @> ARRAY[
              'm={DATABASE_HNSW_M}',
              'ef_construction={DATABASE_HNSW_EF_CONSTRUCTION}'
          ]::text[]
          AND cardinality(
              COALESCE(
                  index_relation.reloptions,
                  ARRAY[]::text[]
              )
          ) = 2
    )
    """
)


@router.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/health/ready")
def readiness_check(
    request: Request,
    response: Response,
) -> dict[str, str | int | float | bool | None]:
    recovery = _job_recovery_status(request)
    storage_deletion = _storage_deletion_status(request)
    provider_requests = _ai_provider_request_status()
    database_timeouts = {
        "database_connect_timeout_seconds": settings.database_connect_timeout_seconds,
        "database_pool_timeout_seconds": settings.database_pool_timeout_seconds,
        "database_statement_timeout_seconds": (
            settings.database_statement_timeout_seconds
        ),
        "database_health_statement_timeout_seconds": (
            settings.database_health_statement_timeout_seconds
        ),
        "hnsw_iterative_scan": "strict_order",
        "hnsw_ef_search": settings.hnsw_ef_search,
        "hnsw_max_scan_tuples": settings.hnsw_max_scan_tuples,
    }
    pool = database_pool_snapshot()
    database_pool = {
        "database_pool_size": pool.pool_size,
        "database_pool_max_overflow": pool.max_overflow,
        "database_pool_capacity": pool.capacity,
        "database_pool_checked_in": pool.checked_in,
        "database_pool_checked_out": pool.checked_out,
        "database_pool_overflow": pool.overflow,
        "database_pool_utilization_percent": pool.utilization_percent,
        "database_pool_saturated": pool.saturated,
    }
    if pool.saturated:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "database": "pool_saturated",
            "vector": "unknown",
            "index": "unknown",
            **database_timeouts,
            **database_pool,
            **provider_requests,
            **recovery,
            **storage_deletion,
        }
    try:
        with SessionLocal() as db:
            set_local_statement_timeout(
                db,
                settings.database_health_statement_timeout_seconds,
            )
            database_ready = db.scalar(text("SELECT 1")) == 1
            vector_ready = bool(
                db.scalar(
                    text(
                        """
                        SELECT COALESCE(
                            (
                                SELECT ROW(
                                    split_part(extversion, '.', 1)::integer,
                                    split_part(extversion, '.', 2)::integer
                                ) >= ROW(0, 8)
                                FROM pg_extension
                                WHERE extname = 'vector'
                            ),
                            false
                        )
                        """
                    )
                )
            )
            index_ready = _hnsw_index_exists(db)
            storage_deletion_queue = (
                storage_deletion_service.storage_deletion_queue_snapshot(db)
            )
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "database": "unavailable",
            "vector": "unknown",
            "index": "unknown",
            **database_timeouts,
            **database_pool,
            **provider_requests,
            **recovery,
            **storage_deletion,
        }

    storage_deletion = _storage_deletion_status(
        request,
        storage_deletion_queue,
    )

    ready = (
        database_ready
        and vector_ready
        and index_ready
        and recovery["job_recovery"] == "ready"
        and storage_deletion["storage_deletion"] == "ready"
    )
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "database": "ready" if database_ready else "unavailable",
        "vector": "ready" if vector_ready else "missing",
        "index": "ready" if index_ready else "missing",
        **database_timeouts,
        **database_pool,
        **provider_requests,
        **recovery,
        **storage_deletion,
    }


@router.get("/health/capabilities")
def capabilities() -> dict:
    provider_requests = provider_request_limiter.snapshot()
    return {
        "ai_provider": {
            "max_response_size_bytes": (
                settings.ai_provider_max_response_size_bytes
            ),
            "max_concurrent_requests": (
                provider_requests.max_concurrent_requests
            ),
            "active_requests": provider_requests.active_requests,
            "waiting_requests": provider_requests.waiting_requests,
        },
        "storage": {
            "backend": settings.storage_backend,
            "enabled": settings.storage_backend in {"local", "s3"},
        },
        "ocr": {
            "provider": settings.ocr_provider,
            "enabled": settings.ocr_provider != "disabled",
        },
        "speech_to_text": {
            "provider": settings.speech_to_text_provider,
            "enabled": settings.speech_to_text_provider != "disabled",
        },
        "embedding": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
            "hnsw_index": _hnsw_index_status(),
            "hnsw_iterative_scan": "strict_order",
            "hnsw_ef_search": settings.hnsw_ef_search,
            "hnsw_max_scan_tuples": settings.hnsw_max_scan_tuples,
        },
    }


def _ai_provider_request_status() -> dict[str, int]:
    snapshot = provider_request_limiter.snapshot()
    return {
        "ai_provider_max_response_size_bytes": (
            settings.ai_provider_max_response_size_bytes
        ),
        "ai_provider_max_concurrent_requests": (
            snapshot.max_concurrent_requests
        ),
        "ai_provider_active_requests": snapshot.active_requests,
        "ai_provider_waiting_requests": snapshot.waiting_requests,
    }


def _hnsw_index_status() -> str:
    try:
        with SessionLocal() as db:
            set_local_statement_timeout(
                db,
                settings.database_health_statement_timeout_seconds,
            )
            return "present" if _hnsw_index_exists(db) else "missing"
    except Exception:
        return "unknown"


def _hnsw_index_exists(db) -> bool:
    return bool(db.scalar(HNSW_INDEX_COMPATIBILITY_SQL))


def _job_recovery_status(request: Request) -> dict[str, str | int | float | None]:
    recovery_state = getattr(request.app.state, "job_recovery_state", None)
    recovery_task = getattr(request.app.state, "job_recovery_loop_task", None)
    snapshot = (
        recovery_state.snapshot()
        if isinstance(recovery_state, JobRecoveryState)
        else None
    )
    now = datetime.now(timezone.utc)
    scan_stale_after_seconds = settings.job_recovery_scan_stale_after_seconds
    freshness_timeout_seconds = max(
        settings.job_recovery_interval_seconds * 3,
        scan_stale_after_seconds * 2,
    )
    scan_overdue = bool(
        snapshot is not None
        and snapshot.scan_started_at is not None
        and (now - snapshot.scan_started_at).total_seconds()
        > scan_stale_after_seconds
    )
    success_stale = bool(
        snapshot is not None
        and snapshot.last_success_at is not None
        and (now - snapshot.last_success_at).total_seconds()
        > freshness_timeout_seconds
    )
    if recovery_task is None or recovery_task.done():
        recovery_status = "stopped"
        recovery_reason = "supervisor_stopped"
    elif snapshot is None:
        recovery_status = "degraded"
        recovery_reason = "state_unavailable"
    elif scan_overdue:
        recovery_status = "degraded"
        recovery_reason = "scan_overdue"
    elif snapshot.consecutive_failures > 0:
        recovery_status = "degraded"
        recovery_reason = "scan_failed"
    elif snapshot.last_success_at is None:
        recovery_status = "degraded"
        recovery_reason = "never_succeeded"
    elif success_stale:
        recovery_status = "degraded"
        recovery_reason = "success_stale"
    else:
        recovery_status = "ready"
        recovery_reason = None
    worker_snapshot = job_worker_limiter.snapshot()
    return {
        "job_recovery": recovery_status,
        "job_recovery_reason": recovery_reason,
        "job_recovery_last_scan_at": (
            snapshot.last_scan_at.isoformat()
            if snapshot is not None and snapshot.last_scan_at is not None
            else None
        ),
        "job_recovery_last_success_at": (
            snapshot.last_success_at.isoformat()
            if snapshot is not None and snapshot.last_success_at is not None
            else None
        ),
        "job_recovery_scan_started_at": (
            snapshot.scan_started_at.isoformat()
            if snapshot is not None and snapshot.scan_started_at is not None
            else None
        ),
        "job_recovery_last_scan_duration_ms": (
            snapshot.last_scan_duration_ms if snapshot is not None else None
        ),
        "job_recovery_consecutive_failures": (
            snapshot.consecutive_failures if snapshot is not None else 0
        ),
        "job_recovery_last_dispatched_jobs": (
            snapshot.last_dispatched_jobs if snapshot is not None else 0
        ),
        "job_recovery_active_workers": (
            snapshot.active_workers if snapshot is not None else 0
        ),
        "job_recovery_max_active_workers": settings.job_recovery_max_active_workers,
        "job_worker_occupied_slots": worker_snapshot.occupied_slots,
        "job_worker_waiting_tasks": worker_snapshot.waiting_tasks,
        "job_worker_max_active_workers": worker_snapshot.max_active_workers,
        "job_recovery_scan_stale_after_seconds": scan_stale_after_seconds,
        "job_recovery_statement_timeout_seconds": (
            settings.job_recovery_statement_timeout_seconds
        ),
        "job_recovery_freshness_timeout_seconds": freshness_timeout_seconds,
    }


def _storage_deletion_status(
    request: Request,
    queue_snapshot: (
        storage_deletion_service.StorageDeletionQueueSnapshot | None
    ) = None,
) -> dict[str, str | int | float | None]:
    deletion_state = getattr(request.app.state, "storage_deletion_state", None)
    deletion_task = getattr(
        request.app.state,
        "storage_deletion_loop_task",
        None,
    )
    snapshot = (
        deletion_state.snapshot()
        if isinstance(deletion_state, StorageDeletionState)
        else None
    )
    now = datetime.now(timezone.utc)
    batch_stale_after_seconds = settings.storage_deletion_lease_seconds
    freshness_timeout_seconds = max(
        settings.storage_deletion_interval_seconds * 3,
        batch_stale_after_seconds * 2,
    )
    batch_overdue = bool(
        snapshot is not None
        and snapshot.batch_started_at is not None
        and (now - snapshot.batch_started_at).total_seconds()
        > batch_stale_after_seconds
    )
    success_stale = bool(
        snapshot is not None
        and snapshot.last_success_at is not None
        and (now - snapshot.last_success_at).total_seconds()
        > freshness_timeout_seconds
    )
    if deletion_task is None or deletion_task.done():
        deletion_status = "stopped"
        deletion_reason = "supervisor_stopped"
    elif snapshot is None:
        deletion_status = "degraded"
        deletion_reason = "state_unavailable"
    elif batch_overdue:
        deletion_status = "degraded"
        deletion_reason = "batch_overdue"
    elif snapshot.consecutive_failures > 0:
        deletion_status = "degraded"
        deletion_reason = "batch_failed"
    elif snapshot.last_success_at is None:
        deletion_status = "degraded"
        deletion_reason = "never_succeeded"
    elif queue_snapshot is not None and queue_snapshot.failed > 0:
        deletion_status = "degraded"
        deletion_reason = "persistent_deletion_failed"
    elif queue_snapshot is not None and queue_snapshot.abandoned > 0:
        deletion_status = "degraded"
        deletion_reason = "abandoned_deletion_lease"
    elif snapshot.last_failed > 0 and (
        queue_snapshot is None or queue_snapshot.pending > 0
    ):
        deletion_status = "degraded"
        deletion_reason = "deletion_failed"
    elif success_stale:
        deletion_status = "degraded"
        deletion_reason = "success_stale"
    else:
        deletion_status = "ready"
        deletion_reason = None
    return {
        "storage_deletion": deletion_status,
        "storage_deletion_reason": deletion_reason,
        "storage_deletion_last_run_at": (
            snapshot.last_run_at.isoformat()
            if snapshot is not None and snapshot.last_run_at is not None
            else None
        ),
        "storage_deletion_last_success_at": (
            snapshot.last_success_at.isoformat()
            if snapshot is not None and snapshot.last_success_at is not None
            else None
        ),
        "storage_deletion_batch_started_at": (
            snapshot.batch_started_at.isoformat()
            if snapshot is not None and snapshot.batch_started_at is not None
            else None
        ),
        "storage_deletion_last_batch_duration_ms": (
            snapshot.last_batch_duration_ms if snapshot is not None else None
        ),
        "storage_deletion_consecutive_failures": (
            snapshot.consecutive_failures if snapshot is not None else 0
        ),
        "storage_deletion_last_claimed": (
            snapshot.last_claimed if snapshot is not None else 0
        ),
        "storage_deletion_last_completed": (
            snapshot.last_completed if snapshot is not None else 0
        ),
        "storage_deletion_last_failed": (
            snapshot.last_failed if snapshot is not None else 0
        ),
        "storage_deletion_queue_pending": (
            queue_snapshot.pending if queue_snapshot is not None else None
        ),
        "storage_deletion_queue_failed": (
            queue_snapshot.failed if queue_snapshot is not None else None
        ),
        "storage_deletion_queue_abandoned": (
            queue_snapshot.abandoned if queue_snapshot is not None else None
        ),
        "storage_deletion_queue_active_leases": (
            queue_snapshot.active_leases
            if queue_snapshot is not None
            else None
        ),
        "storage_deletion_queue_eligible": (
            queue_snapshot.eligible if queue_snapshot is not None else None
        ),
        "storage_deletion_queue_oldest_created_at": (
            queue_snapshot.oldest_created_at.isoformat()
            if queue_snapshot is not None
            and queue_snapshot.oldest_created_at is not None
            else None
        ),
        "storage_deletion_queue_earliest_next_attempt_at": (
            queue_snapshot.earliest_next_attempt_at.isoformat()
            if queue_snapshot is not None
            and queue_snapshot.earliest_next_attempt_at is not None
            else None
        ),
        "storage_deletion_batch_size": settings.storage_deletion_batch_size,
        "storage_deletion_interval_seconds": (
            settings.storage_deletion_interval_seconds
        ),
        "storage_deletion_lease_seconds": batch_stale_after_seconds,
        "storage_deletion_statement_timeout_seconds": (
            settings.storage_deletion_statement_timeout_seconds
        ),
        "storage_deletion_freshness_timeout_seconds": freshness_timeout_seconds,
    }
