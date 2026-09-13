from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only, with_expression

from app.core.config import settings
from app.core.request_limits import USER_AVATAR_URL_MAX_LENGTH
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models.auth_registration_invite import AuthRegistrationInvite
from app.models.auth_session import AuthSession
from app.models.chunk import DocumentChunk
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.embedding import ChunkEmbedding
from app.models.job import Job
from app.models.message import Message
from app.models.tag import DocumentTag, Tag
from app.models.user import User
from app.schemas.auth import (
    AccountDelete,
    AuthResponse,
    AuthSessionRead,
    PasswordChange,
    UserLogin,
    UserRead,
    UserRegister,
)
from app.services import storage_deletion_service
from app.services.login_rate_limit_service import (
    LoginRateLimiter,
    RegistrationRateLimiter,
    login_rate_limiter,
    registration_rate_limiter,
)
from app.services.registration_invite_service import registration_invite_hash

_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


class LoginRateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("登录尝试过于频繁，请稍后重试")


class InvalidCredentialsError(ValueError):
    pass


class EmailAlreadyRegisteredError(ValueError):
    pass


class RegistrationRateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("注册请求过于频繁，请稍后重试")


class RegistrationInviteInvalidError(ValueError):
    pass


class CurrentPasswordInvalidError(ValueError):
    pass


class PasswordReuseError(ValueError):
    pass


class AuthSessionNotFoundError(LookupError):
    pass


class UserNotFoundError(LookupError):
    pass


class AdminAccountDeletionError(RuntimeError):
    pass


class AccountDataOwnershipError(RuntimeError):
    pass


def register(
    db: Session,
    payload: UserRegister,
    client_host: str | None = None,
    client_name: str | None = None,
    *,
    limiter: RegistrationRateLimiter = registration_rate_limiter,
    invite_required: bool | None = None,
) -> AuthResponse:
    retry_after = limiter.consume(db, client_host=client_host)
    if retry_after is not None:
        raise RegistrationRateLimitedError(retry_after)

    requires_invite = (
        settings.registration_invite_required
        if invite_required is None
        else invite_required
    )
    invite = (
        _lock_valid_registration_invite(db, payload.invite_code)
        if requires_invite
        else None
    )

    email = payload.email.lower()
    existing = db.scalar(select(User.id).where(User.email == email))
    if existing:
        raise EmailAlreadyRegisteredError("邮箱已注册")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        name=payload.name,
    )
    db.add(user)
    try:
        db.flush()
        access_token = _issue_access_token(db, user, client_name=client_name)
        if invite is not None:
            invite.used_at = datetime.now(UTC)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _integrity_constraint_name(exc) == "uq_users_email":
            raise EmailAlreadyRegisteredError("邮箱已注册") from exc
        raise
    db.refresh(user)
    return AuthResponse(access_token=access_token, user=_user_read(user))


def _lock_valid_registration_invite(
    db: Session,
    code: str | None,
) -> AuthRegistrationInvite:
    if code is None or not code.strip():
        raise RegistrationInviteInvalidError("邀请码无效或已过期")
    invite = db.scalar(
        select(AuthRegistrationInvite)
        .where(
            AuthRegistrationInvite.code_hash == registration_invite_hash(code)
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.used_at is not None
        or invite.revoked_at is not None
        or invite.expires_at <= now
    ):
        raise RegistrationInviteInvalidError("邀请码无效或已过期")
    return invite


def login(
    db: Session,
    payload: UserLogin,
    client_host: str | None = None,
    client_name: str | None = None,
    *,
    limiter: LoginRateLimiter = login_rate_limiter,
) -> AuthResponse:
    email = payload.email.lower()
    retry_after = limiter.check_retry_after(
        db,
        email=email,
        client_host=client_host,
    )
    if retry_after is not None:
        raise LoginRateLimitedError(retry_after)

    user = db.scalar(_user_auth_statement().where(User.email == email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(payload.password, password_hash)
    if user is None or not password_matches:
        retry_after = limiter.record_failure(
            db,
            email=email,
            client_host=client_host,
        )
        if retry_after is not None:
            raise LoginRateLimitedError(retry_after)
        raise InvalidCredentialsError("邮箱或密码错误")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    limiter.clear_account_failures(db, email=email)
    access_token = _issue_access_token(db, user, client_name=client_name)
    db.commit()
    return AuthResponse(access_token=access_token, user=_user_read(user))


def logout(db: Session, *, user_id: UUID, session_id: UUID) -> None:
    db.execute(
        delete(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
        )
    )
    db.commit()


def logout_all(db: Session, *, user_id: UUID) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()


def change_password(
    db: Session,
    *,
    user_id: UUID,
    payload: PasswordChange,
    client_host: str | None = None,
    client_name: str | None = None,
    limiter: LoginRateLimiter = login_rate_limiter,
) -> AuthResponse:
    user = db.scalar(
        _user_auth_statement().where(User.id == user_id).with_for_update()
    )
    if user is None:
        raise UserNotFoundError("用户不存在")

    retry_after = limiter.check_retry_after(
        db,
        email=user.email,
        client_host=client_host,
    )
    if retry_after is not None:
        raise LoginRateLimitedError(retry_after)

    if not verify_password(payload.current_password, user.password_hash):
        retry_after = limiter.record_failure(
            db,
            email=user.email,
            client_host=client_host,
        )
        if retry_after is not None:
            raise LoginRateLimitedError(retry_after)
        raise CurrentPasswordInvalidError("当前密码错误")
    if payload.new_password == payload.current_password:
        raise PasswordReuseError("新密码不能与当前密码相同")

    user.password_hash = hash_password(payload.new_password)
    limiter.clear_account_failures(db, email=user.email)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    access_token = _issue_access_token(db, user, client_name=client_name)
    db.commit()
    return AuthResponse(access_token=access_token, user=_user_read(user))


def delete_account(
    db: Session,
    *,
    user_id: UUID,
    payload: AccountDelete,
    client_host: str | None = None,
    limiter: LoginRateLimiter = login_rate_limiter,
) -> None:
    user = db.scalar(
        _user_deletion_statement()
        .where(User.id == user_id)
        .with_for_update()
    )
    if user is None:
        raise UserNotFoundError("用户不存在")
    if user.id == settings.runtime_settings_admin_user_id:
        raise AdminAccountDeletionError(
            "管理员账号不能自助删除，请先调整管理员用户配置"
        )

    retry_after = limiter.check_retry_after(
        db,
        email=user.email,
        client_host=client_host,
    )
    if retry_after is not None:
        raise LoginRateLimitedError(retry_after)
    if not verify_password(payload.current_password, user.password_hash):
        retry_after = limiter.record_failure(
            db,
            email=user.email,
            client_host=client_host,
        )
        if retry_after is not None:
            raise LoginRateLimitedError(retry_after)
        raise CurrentPasswordInvalidError("当前密码错误")

    if _has_user_data_ownership_conflict(db, user.id):
        raise AccountDataOwnershipError(
            "账号数据归属异常，暂时不能删除，请联系管理员处理"
        )

    _lock_account_deletion_rows(db, user.id)
    if _has_missing_document_storage_provenance(db, user.id):
        raise AccountDataOwnershipError(
            "账号资料缺少存储位置信息，暂时不能删除，请联系管理员处理"
        )
    storage_deletion_service.enqueue_document_storage_deletions(
        db,
        user_id=user.id,
    )

    db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.user_id == user.id))
    db.execute(delete(DocumentChunk).where(DocumentChunk.user_id == user.id))
    db.execute(delete(Message).where(Message.user_id == user.id))
    db.execute(delete(Job).where(Job.user_id == user.id))
    db.execute(delete(Conversation).where(Conversation.user_id == user.id))
    db.execute(delete(Document).where(Document.user_id == user.id))
    db.execute(delete(Tag).where(Tag.user_id == user.id))
    limiter.clear_account_failures(db, email=user.email)
    db.delete(user)
    db.commit()


def _lock_account_deletion_rows(db: Session, user_id: UUID) -> None:
    for model, cte_name in (
        (Job, "locked_account_jobs"),
        (Document, "locked_account_documents"),
    ):
        locked_rows = (
            select(model.id)
            .where(model.user_id == user_id)
            .order_by(model.id)
            .with_for_update()
            .cte(cte_name)
        )
        db.scalar(select(func.count()).select_from(locked_rows))


def _has_missing_document_storage_provenance(
    db: Session,
    user_id: UUID,
) -> bool:
    missing_provenance = (
        select(Document.id)
        .where(
            Document.user_id == user_id,
            Document.file_path.is_not(None),
            Document.file_path != "",
            or_(
                Document.storage_backend.is_(None),
                Document.storage_backend == "",
                Document.storage_scope.is_(None),
                Document.storage_scope == "",
            ),
        )
        .limit(1)
        .exists()
    )
    return bool(db.scalar(select(missing_provenance)))


def _has_user_data_ownership_conflict(db: Session, user_id: UUID) -> bool:
    checks = (
        select(DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.user_id != Document.user_id,
            or_(
                DocumentChunk.user_id == user_id,
                Document.user_id == user_id,
            ),
        )
        .limit(1),
        select(ChunkEmbedding.id)
        .join(Document, Document.id == ChunkEmbedding.document_id)
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(
            or_(
                ChunkEmbedding.user_id != Document.user_id,
                ChunkEmbedding.user_id != DocumentChunk.user_id,
                ChunkEmbedding.document_id != DocumentChunk.document_id,
            ),
            or_(
                ChunkEmbedding.user_id == user_id,
                Document.user_id == user_id,
                DocumentChunk.user_id == user_id,
            ),
        )
        .limit(1),
        select(Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.user_id != Conversation.user_id,
            or_(
                Message.user_id == user_id,
                Conversation.user_id == user_id,
            ),
        )
        .limit(1),
        select(Job.id)
        .join(Document, Document.id == Job.document_id)
        .where(
            Job.user_id != Document.user_id,
            or_(Job.user_id == user_id, Document.user_id == user_id),
        )
        .limit(1),
        select(DocumentTag.document_id)
        .join(Document, Document.id == DocumentTag.document_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(
            Document.user_id != Tag.user_id,
            or_(Document.user_id == user_id, Tag.user_id == user_id),
        )
        .limit(1),
    )
    return any(db.scalar(statement) is not None for statement in checks)


def list_sessions(
    db: Session,
    *,
    user_id: UUID,
    current_session_id: UUID,
) -> list[AuthSessionRead]:
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
        .limit(settings.auth_max_active_sessions_per_user)
    ).all()
    return [
        AuthSessionRead(
            id=session.id,
            client_name=session.client_name,
            created_at=session.created_at,
            expires_at=session.expires_at,
            is_current=session.id == current_session_id,
        )
        for session in sessions
    ]


def revoke_session(db: Session, *, user_id: UUID, session_id: UUID) -> None:
    deleted_session_id = db.scalar(
        delete(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
        )
        .returning(AuthSession.id)
    )
    if deleted_session_id is None:
        raise AuthSessionNotFoundError("登录会话不存在")
    db.commit()


def get_user(db: Session, user_id: UUID) -> UserRead | None:
    user = db.scalar(_user_public_statement().where(User.id == user_id))
    return _user_read(user) if user is not None else None


def _user_read(user: User) -> UserRead:
    missing = object()
    avatar_url = getattr(user, "avatar_url_preview", missing)
    if avatar_url is missing:
        raw_avatar_url = getattr(user, "avatar_url", None)
        avatar_url = (
            raw_avatar_url[:USER_AVATAR_URL_MAX_LENGTH]
            if raw_avatar_url
            else None
        )
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=avatar_url,
        is_admin=user.id == settings.runtime_settings_admin_user_id,
        created_at=user.created_at,
    )


def _user_public_statement():
    return select(User).options(
        load_only(
            User.id,
            User.email,
            User.name,
            User.created_at,
            raiseload=True,
        ),
        with_expression(
            User.avatar_url_preview,
            func.left(User.avatar_url, USER_AVATAR_URL_MAX_LENGTH),
        ),
    )


def _user_auth_statement():
    return select(User).options(
        load_only(
            User.id,
            User.email,
            User.password_hash,
            User.name,
            User.created_at,
            raiseload=True,
        ),
        with_expression(
            User.avatar_url_preview,
            func.left(User.avatar_url, USER_AVATAR_URL_MAX_LENGTH),
        ),
    )


def _user_deletion_statement():
    return select(User).options(
        load_only(
            User.id,
            User.email,
            User.password_hash,
            raiseload=True,
        )
    )


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diagnostics = getattr(exc.orig, "diag", None)
    constraint_name = getattr(diagnostics, "constraint_name", None)
    return constraint_name if isinstance(constraint_name, str) else None


def _issue_access_token(
    db: Session,
    user: User,
    *,
    client_name: str | None = None,
) -> str:
    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    locked_user_id = db.scalar(
        select(User.id).where(User.id == user.id).with_for_update()
    )
    if locked_user_id is None:
        raise RuntimeError("cannot create a session for a missing user")

    retained_existing_sessions = settings.auth_max_active_sessions_per_user - 1
    stale_sessions = (
        select(AuthSession.id)
        .where(AuthSession.user_id == user.id)
        .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
        .offset(retained_existing_sessions)
        .cte("stale_auth_sessions")
    )
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.id.in_(select(stale_sessions.c.id)),
        )
    )

    session_id = uuid4()
    db.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            expires_at=expires_at,
            client_name=client_name,
        )
    )
    return create_access_token(
        user.id,
        session_id,
        issued_at=now,
        expires_at=expires_at,
    )
