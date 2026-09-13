import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_registration_invite import AuthRegistrationInvite

INVITE_RANDOM_BYTES = 32


@dataclass(frozen=True)
class CreatedRegistrationInvite:
    code: str
    invite: AuthRegistrationInvite


def registration_invite_hash(
    code: str,
    *,
    secret_key: str | None = None,
) -> str:
    normalized_code = code.strip()
    if not normalized_code:
        raise ValueError("registration invite code must not be blank")
    key = (secret_key or settings.auth_secret_key).encode("utf-8")
    return hmac.new(
        key,
        normalized_code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_registration_invite(
    db: Session,
    *,
    valid_for: timedelta,
    now: datetime | None = None,
    code: str | None = None,
) -> CreatedRegistrationInvite:
    if valid_for <= timedelta(0):
        raise ValueError("registration invite validity must be positive")
    issued_at = now or datetime.now(UTC)
    raw_code = code or secrets.token_urlsafe(INVITE_RANDOM_BYTES)
    invite = AuthRegistrationInvite(
        code_hash=registration_invite_hash(raw_code),
        expires_at=issued_at + valid_for,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return CreatedRegistrationInvite(code=raw_code, invite=invite)
