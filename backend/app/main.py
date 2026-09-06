import asyncio
import logging
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import PRIVATE_RESPONSE_HEADERS, register_exception_handlers
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.workers.job_recovery import (
    JobRecoveryState,
    JobRecoveryTaskRegistry,
    run_recovery_loop,
    schedule_recoverable_jobs,
)
from app.workers.storage_deletion import (
    StorageDeletionState,
    StorageDeletionTaskRegistry,
    StorageDeletionWakeup,
    run_storage_deletion_loop,
    schedule_storage_deletion_batch,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    recovery_state = JobRecoveryState()
    task_registry = JobRecoveryTaskRegistry()
    storage_deletion_state = StorageDeletionState()
    storage_deletion_registry = StorageDeletionTaskRegistry()
    storage_deletion_wakeup = StorageDeletionWakeup()
    app.state.job_recovery_state = recovery_state
    app.state.job_recovery_task_registry = task_registry
    app.state.storage_deletion_task_registry = storage_deletion_registry
    app.state.storage_deletion_state = storage_deletion_state
    app.state.storage_deletion_wakeup = storage_deletion_wakeup
    recovery_state.record_scan_started()
    try:
        app.state.recovered_job_tasks = await schedule_recoverable_jobs(
            state=recovery_state,
            task_registry=task_registry,
        )
    except asyncio.CancelledError:
        recovery_state.record_scan_cancelled()
        raise
    except Exception:
        recovery_state.record_failure()
        raise
    else:
        recovery_state.record_success()
    recovery_loop_task = asyncio.create_task(
        run_recovery_loop(recovery_state, task_registry)
    )
    app.state.job_recovery_loop_task = recovery_loop_task
    app.state.storage_deletion_tasks = schedule_storage_deletion_batch(
        storage_deletion_registry,
        storage_deletion_state,
    )
    storage_deletion_loop_task = asyncio.create_task(
        run_storage_deletion_loop(
            storage_deletion_registry,
            storage_deletion_state,
            storage_deletion_wakeup,
        )
    )
    app.state.storage_deletion_loop_task = storage_deletion_loop_task
    try:
        yield
    finally:
        recovery_loop_task.cancel()
        storage_deletion_loop_task.cancel()
        for loop_task in (recovery_loop_task, storage_deletion_loop_task):
            with suppress(asyncio.CancelledError):
                await loop_task
        workers_completed = await task_registry.wait_for_completion(
            settings.job_recovery_shutdown_timeout_seconds
        )
        if not workers_completed:
            logger.warning(
                "Recovery workers exceeded the shutdown timeout and were cancelled"
            )
        deletions_completed = await storage_deletion_registry.wait_for_completion(
            settings.storage_deletion_shutdown_timeout_seconds
        )
        if not deletions_completed:
            logger.warning(
                "Storage deletion workers exceeded the shutdown timeout and were cancelled"
            )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=False,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_size_bytes=settings.max_request_body_size_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count", "X-Embedding-Rebuild-Job-Id"],
    )

    @app.middleware("http")
    async def disable_api_response_caching(request: Request, call_next):
        response = await call_next(request)
        if _is_api_path(request.url.path):
            for name, value in PRIVATE_RESPONSE_HEADERS.items():
                response.headers[name] = value
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


def _is_api_path(path: str) -> bool:
    prefix = settings.api_prefix.rstrip("/")
    return path == prefix or path.startswith(f"{prefix}/")


app = create_app()
