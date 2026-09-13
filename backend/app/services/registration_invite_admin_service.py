from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.pagination import offset_for_page
from app.models.auth_registration_invite import AuthRegistrationInvite
from app.schemas.registration_invite import (
    RegistrationInviteCreatedRead,
    RegistrationInvitePageRead,
    RegistrationInviteRead,
    RegistrationInviteStatus,
)
from app.services.registration_invite_service import create_registration_invite


class RegistrationInviteNotFoundError(LookupError):
    pass


class RegistrationInviteNotRevocableError(ValueError):
    pass


class RegistrationInviteAccessError(PermissionError):
    pass


def ensure_registration_invite_admin(user_id: UUID) -> None:
    if user_id != settings.runtime_settings_admin_user_id:
        raise RegistrationInviteAccessError("只有管理员可以管理注册邀请码")


def list_registration_invites(
    db: Session,
    *,
    user_id: UUID,
    page: int,
    page_size: int,
    invite_status: RegistrationInviteStatus | None = None,
) -> RegistrationInvitePageRead:
    ensure_registration_invite_admin(user_id)
    offset = offset_for_page(page, page_size)
    now = datetime.now(UTC)
    conditions = _status_conditions(invite_status, now)
    total = db.scalar(
        select(func.count(AuthRegistrationInvite.id)).where(*conditions)
    ) or 0
    invites = db.scalars(
        select(AuthRegistrationInvite)
        .where(*conditions)
        .order_by(
            AuthRegistrationInvite.created_at.desc(),
            AuthRegistrationInvite.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    ).all()
    return RegistrationInvitePageRead(
        items=[_invite_read(invite, now) for invite in invites],
        total=total,
        page=page,
        page_size=page_size,
    )


def create_managed_registration_invite(
    db: Session,
    *,
    user_id: UUID,
    valid_hours: int,
) -> RegistrationInviteCreatedRead:
    ensure_registration_invite_admin(user_id)
    created = create_registration_invite(
        db,
        valid_for=timedelta(hours=valid_hours),
    )
    invite_read = _invite_read(created.invite, datetime.now(UTC))
    return RegistrationInviteCreatedRead(
        **invite_read.model_dump(),
        code=created.code,
    )


def revoke_registration_invite(
    db: Session,
    *,
    user_id: UUID,
    invite_id: UUID,
) -> None:
    ensure_registration_invite_admin(user_id)
    invite = db.scalar(
        select(AuthRegistrationInvite)
        .where(AuthRegistrationInvite.id == invite_id)
        .with_for_update()
    )
    if invite is None:
        raise RegistrationInviteNotFoundError("注册邀请码不存在")
    if invite.revoked_at is not None:
        db.commit()
        return
    now = datetime.now(UTC)
    if invite.used_at is not None or invite.expires_at <= now:
        raise RegistrationInviteNotRevocableError("已使用或已过期的邀请码不能撤销")
    invite.revoked_at = now
    db.commit()


def _status_conditions(
    invite_status: RegistrationInviteStatus | None,
    now: datetime,
) -> tuple:
    if invite_status is None:
        return ()
    if invite_status is RegistrationInviteStatus.USED:
        return (AuthRegistrationInvite.used_at.is_not(None),)
    if invite_status is RegistrationInviteStatus.REVOKED:
        return (AuthRegistrationInvite.revoked_at.is_not(None),)
    available = (
        AuthRegistrationInvite.used_at.is_(None),
        AuthRegistrationInvite.revoked_at.is_(None),
    )
    if invite_status is RegistrationInviteStatus.ACTIVE:
        return (*available, AuthRegistrationInvite.expires_at > now)
    return (*available, AuthRegistrationInvite.expires_at <= now)


def _invite_read(
    invite: AuthRegistrationInvite,
    now: datetime,
) -> RegistrationInviteRead:
    if invite.used_at is not None:
        invite_status = RegistrationInviteStatus.USED
    elif invite.revoked_at is not None:
        invite_status = RegistrationInviteStatus.REVOKED
    elif invite.expires_at <= now:
        invite_status = RegistrationInviteStatus.EXPIRED
    else:
        invite_status = RegistrationInviteStatus.ACTIVE
    return RegistrationInviteRead(
        id=invite.id,
        status=invite_status,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        revoked_at=invite.revoked_at,
    )
