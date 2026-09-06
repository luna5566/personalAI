from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.output_validation import (
    PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
    ProviderOutputTooLargeError,
)
from app.api.deps import authenticated_user_id, db_session
from app.schemas.organize import (
    OrganizeCollectionRequest,
    OrganizeDocumentRequest,
    OrganizeResponse,
    OrganizeResultSaveRequest,
    OrganizeResultSaveResponse,
)
from app.services import organize_service
from app.services.login_rate_limit_service import ai_user_rate_limiter

router = APIRouter(prefix="/organize", tags=["organize"])
AI_RATE_LIMIT_MESSAGE = "请求过于频繁，请稍后再试"


def _consume_ai_user_quota(
    db: Session,
    user_id: UUID,
) -> None:
    retry_after = ai_user_rate_limiter.consume(db, user_id=user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AI_RATE_LIMIT_MESSAGE,
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/document", response_model=OrganizeResponse)
def organize_document(
    payload: OrganizeDocumentRequest,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> OrganizeResponse:
    _consume_ai_user_quota(db, user_id)
    try:
        return organize_service.organize_document(db, user_id, payload)
    except organize_service.OrganizeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except organize_service.OrganizeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProviderOutputTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
        ) from exc


@router.post("/collection", response_model=OrganizeResponse)
def organize_collection(
    payload: OrganizeCollectionRequest,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> OrganizeResponse:
    _consume_ai_user_quota(db, user_id)
    try:
        return organize_service.organize_collection(db, user_id, payload)
    except organize_service.OrganizeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except organize_service.OrganizeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except organize_service.OrganizeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderOutputTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE,
        ) from exc


@router.post(
    "/save-result",
    response_model=OrganizeResultSaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_organize_result(
    payload: OrganizeResultSaveRequest,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> OrganizeResultSaveResponse:
    try:
        return organize_service.save_organize_result(db, user_id, payload)
    except organize_service.OrganizeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
