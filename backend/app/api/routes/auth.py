from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedAccess, authenticated_access, authenticated_user_id, db_session
from app.core.config import settings
from app.schemas.auth import (
    AccountDelete,
    AuthConfigRead,
    AuthResponse,
    AuthSessionRead,
    PasswordChange,
    UserLogin,
    UserRead,
    UserRegister,
)
from app.services import auth_service
from app.workers.storage_deletion import StorageDeletionWakeup

router = APIRouter(prefix="/auth", tags=["auth"])
CLIENT_NAME_MAX_LENGTH = 128
REGISTRATION_DISABLED_MESSAGE = "当前不开放新账号注册"


@router.get("/config", response_model=AuthConfigRead)
def auth_config(response: Response) -> AuthConfigRead:
    response.headers["Cache-Control"] = "no-store"
    return AuthConfigRead(
        registration_enabled=settings.registration_enabled,
        invitation_required=(
            settings.registration_enabled
            and settings.registration_invite_required
        ),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegister,
    request: Request,
    db: Annotated[Session, Depends(db_session)],
) -> AuthResponse:
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=REGISTRATION_DISABLED_MESSAGE,
        )
    client_host = request.client.host if request.client is not None else None
    try:
        return auth_service.register(
            db,
            payload,
            client_host,
            client_name=_client_name(request),
        )
    except auth_service.RegistrationRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except auth_service.RegistrationInviteInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except auth_service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/login", response_model=AuthResponse)
def login(
    payload: UserLogin,
    request: Request,
    db: Annotated[Session, Depends(db_session)],
) -> AuthResponse:
    client_host = request.client.host if request.client is not None else None
    try:
        return auth_service.login(
            db,
            payload,
            client_host,
            client_name=_client_name(request),
        )
    except auth_service.LoginRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except auth_service.InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> None:
    auth_service.logout(
        db,
        user_id=access.user_id,
        session_id=access.session_id,
    )


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> None:
    auth_service.logout_all(db, user_id=access.user_id)


@router.post("/change-password", response_model=AuthResponse)
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> AuthResponse:
    client_host = request.client.host if request.client is not None else None
    try:
        return auth_service.change_password(
            db,
            user_id=access.user_id,
            payload=payload,
            client_host=client_host,
            client_name=_client_name(request),
        )
    except auth_service.LoginRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except (
        auth_service.CurrentPasswordInvalidError,
        auth_service.PasswordReuseError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except auth_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: AccountDelete,
    request: Request,
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> None:
    client_host = request.client.host if request.client is not None else None
    try:
        auth_service.delete_account(
            db,
            user_id=access.user_id,
            payload=payload,
            client_host=client_host,
        )
    except auth_service.LoginRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except auth_service.CurrentPasswordInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (
        auth_service.AdminAccountDeletionError,
        auth_service.AccountDataOwnershipError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except auth_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    storage_deletion_wakeup = getattr(
        request.app.state,
        "storage_deletion_wakeup",
        None,
    )
    if isinstance(storage_deletion_wakeup, StorageDeletionWakeup):
        storage_deletion_wakeup.notify()


@router.get("/sessions", response_model=list[AuthSessionRead])
def sessions(
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> list[AuthSessionRead]:
    return auth_service.list_sessions(
        db,
        user_id=access.user_id,
        current_session_id=access.session_id,
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_session(
    session_id: UUID,
    db: Annotated[Session, Depends(db_session)],
    access: Annotated[AuthenticatedAccess, Depends(authenticated_access)],
) -> None:
    try:
        auth_service.revoke_session(
            db,
            user_id=access.user_id,
            session_id=session_id,
        )
    except auth_service.AuthSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/me", response_model=UserRead)
def me(
    db: Annotated[Session, Depends(db_session)],
    user_id: Annotated[UUID, Depends(authenticated_user_id)],
) -> UserRead:
    user = auth_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


def _client_name(request: Request) -> str | None:
    raw_value = request.headers.get("X-Client-Name")
    if raw_value is None:
        return None
    normalized = " ".join(raw_value.split())[:CLIENT_NAME_MAX_LENGTH]
    return normalized or None
