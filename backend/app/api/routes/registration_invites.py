from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import authenticated_user_id, db_session
from app.core.pagination import MAX_PAGE_NUMBER
from app.schemas.registration_invite import (
    RegistrationInviteCreate,
    RegistrationInviteCreatedRead,
    RegistrationInvitePageRead,
    RegistrationInviteStatus,
)
from app.services import registration_invite_admin_service

router = APIRouter(prefix="/auth/registration-invites", tags=["auth"])


@router.get("", response_model=RegistrationInvitePageRead)
def list_registration_invites(
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    invite_status: Annotated[
        RegistrationInviteStatus | None,
        Query(alias="status"),
    ] = None,
) -> RegistrationInvitePageRead:
    response.headers["Cache-Control"] = "no-store"
    try:
        return registration_invite_admin_service.list_registration_invites(
            db,
            user_id=user_id,
            page=page,
            page_size=page_size,
            invite_status=invite_status,
        )
    except registration_invite_admin_service.RegistrationInviteAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post(
    "",
    response_model=RegistrationInviteCreatedRead,
    status_code=status.HTTP_201_CREATED,
)
def create_registration_invite(
    payload: RegistrationInviteCreate,
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> RegistrationInviteCreatedRead:
    response.headers["Cache-Control"] = "no-store"
    try:
        return registration_invite_admin_service.create_managed_registration_invite(
            db,
            user_id=user_id,
            valid_hours=payload.valid_hours,
        )
    except registration_invite_admin_service.RegistrationInviteAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_registration_invite(
    invite_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> None:
    try:
        registration_invite_admin_service.revoke_registration_invite(
            db,
            user_id=user_id,
            invite_id=invite_id,
        )
    except registration_invite_admin_service.RegistrationInviteAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except registration_invite_admin_service.RegistrationInviteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except registration_invite_admin_service.RegistrationInviteNotRevocableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
