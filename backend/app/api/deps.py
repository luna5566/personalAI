from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.auth_session import AuthSession
from app.models.user import User


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


optional_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedAccess:
    user_id: UUID
    session_id: UUID


def authenticated_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(db_session),
) -> AuthenticatedAccess:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise _unauthorized() from exc
    access_row = db.execute(
        select(AuthSession.expires_at)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.id == claims.session_id,
            AuthSession.user_id == claims.user_id,
        )
    ).one_or_none()
    if (
        access_row is None
        or access_row.expires_at <= datetime.now(timezone.utc)
    ):
        raise _unauthorized()
    return AuthenticatedAccess(
        user_id=claims.user_id,
        session_id=claims.session_id,
    )


def authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: Session = Depends(db_session),
) -> UUID:
    return authenticated_access(credentials, db).user_id


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态无效或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
