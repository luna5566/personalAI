from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import authenticated_user_id, db_session
from app.core.pagination import MAX_PAGE_NUMBER
from app.models.job import JobStatus, JobType
from app.schemas.job import JobListResponse, JobRead
from app.services import (
    embedding_configuration_service,
    job_service,
    settings_service,
)
from app.workers.document_pipeline import process_document, rebuild_embeddings
from app.workers.job_execution import run_job_with_worker_limit

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type: JobType | None = None,
) -> JobListResponse:
    items, total = job_service.list_jobs(
        db,
        user_id,
        page=page,
        page_size=page_size,
        status=status_filter,
        job_type=job_type,
    )
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/rebuild-embeddings", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def start_rebuild_embeddings(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> JobRead:
    job = job_service.create_job(db, user_id, None, JobType.REBUILD_EMBEDDINGS)
    background_tasks.add_task(
        run_job_with_worker_limit,
        rebuild_embeddings,
        job.id,
        user_id,
    )
    return job_service.to_job_view(job)


@router.post(
    "/rebuild-all-embeddings",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def start_rebuild_all_embeddings(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> JobRead:
    try:
        settings_service.ensure_runtime_settings_access(user_id)
    except settings_service.RuntimeSettingsAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    job = embedding_configuration_service.reconcile_embedding_configuration(
        db,
        user_id,
    )
    if job is None:
        job = job_service.create_job(
            db,
            user_id,
            None,
            JobType.REBUILD_ALL_EMBEDDINGS,
            configuration_fingerprint=(
                settings_service.embedding_configuration_fingerprint()
            ),
        )
    background_tasks.add_task(
        run_job_with_worker_limit,
        rebuild_embeddings,
        job.id,
        None,
    )
    return job_service.to_job_view(job)


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> JobRead:
    try:
        return job_service.to_job_view(
            job_service.cancel_job(db, user_id, job_id)
        )
    except job_service.JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except job_service.JobConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def retry_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> JobRead:
    try:
        original = job_service.get_job(db, user_id, job_id)
        if original is None:
            raise job_service.JobNotFoundError("任务不存在")
        global_rebuild = original.job_type == JobType.REBUILD_ALL_EMBEDDINGS.value
        if global_rebuild:
            settings_service.ensure_runtime_settings_access(user_id)
        if global_rebuild:
            retry, _ = job_service.create_retry_job(
                db,
                user_id,
                job_id,
                configuration_fingerprint=(
                    settings_service.embedding_configuration_fingerprint()
                ),
            )
            embedding_configuration_service.reconcile_embedding_configuration(
                db,
                user_id,
            )
        else:
            retry, _ = job_service.create_retry_job(db, user_id, job_id)
        job_type = JobType(retry.job_type)
        if job_type == JobType.REBUILD_ALL_EMBEDDINGS:
            background_tasks.add_task(
                run_job_with_worker_limit,
                rebuild_embeddings,
                retry.id,
                None,
            )
        elif job_type == JobType.REBUILD_EMBEDDINGS:
            background_tasks.add_task(
                run_job_with_worker_limit,
                rebuild_embeddings,
                retry.id,
                user_id,
            )
        else:
            if retry.document_id is None:
                raise job_service.JobConflictError("原资料已删除，无法重试")
            background_tasks.add_task(
                run_job_with_worker_limit,
                process_document,
                retry.id,
                retry.document_id,
            )
        return job_service.to_job_view(retry)
    except job_service.JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except settings_service.RuntimeSettingsAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except job_service.JobConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> JobRead:
    job = job_service.get_job(db, user_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return job_service.to_job_view(job)
