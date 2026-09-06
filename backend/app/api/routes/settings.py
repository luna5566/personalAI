from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import authenticated_user_id, db_session
from app.schemas.settings import RuntimeSettingsRead, RuntimeSettingsUpdate
from app.services import embedding_configuration_service, settings_service
from app.workers.document_pipeline import rebuild_embeddings
from app.workers.job_execution import run_job_with_worker_limit

router = APIRouter(prefix="/settings", tags=["settings"])
EMBEDDING_REBUILD_JOB_HEADER = "X-Embedding-Rebuild-Job-Id"


@router.get("/runtime", response_model=RuntimeSettingsRead)
def runtime_settings(
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> RuntimeSettingsRead:
    try:
        settings_service.ensure_runtime_settings_access(user_id)
        return settings_service.runtime_settings_read()
    except settings_service.RuntimeSettingsAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/runtime", response_model=RuntimeSettingsRead)
def update_runtime_settings(
    payload: RuntimeSettingsUpdate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> RuntimeSettingsRead:
    try:
        settings_service.ensure_runtime_settings_access(user_id, write=True)
        updated_settings = settings_service.update_runtime_settings(payload)
        job = embedding_configuration_service.reconcile_embedding_configuration(
            db,
            user_id,
        )
        if job is not None:
            response.headers[EMBEDDING_REBUILD_JOB_HEADER] = str(job.id)
            background_tasks.add_task(
                run_job_with_worker_limit,
                rebuild_embeddings,
                job.id,
                None,
            )
        return updated_settings
    except settings_service.RuntimeSettingsAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except settings_service.RuntimeSettingsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
